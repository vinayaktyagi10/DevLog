"""
DevLog Chat Manager - Complete Rewrite with Deep Search + Smart Tool Routing
"""

import asyncio
import subprocess
from typing import Optional, AsyncGenerator, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from devlog.analysis.llm import analyze_code, LLMConfig
from devlog.core.search_unified import smart_search
from devlog.search.web_search import WebSearcher
from devlog.analysis.tool_router import ToolRouter, Intent, ToolType, ToolDecision


@dataclass
class ConversationContext:
    user_name: str
    user_email: str
    current_date: str
    recent_commits: str
    repo_info: str


@dataclass
class Message:
    role: str
    content: str
    tool_name: Optional[str] = None


class ChatManager:
    def __init__(self, model: str = LLMConfig.MODEL):
        self.model = model
        self.history: List[Message] = []
        self.web = WebSearcher()
        self.router = ToolRouter()
        self.max_history = 5
        self.context_cache: Optional[ConversationContext] = None
        self.context_cache_time: Optional[datetime] = None

    def _get_context(self) -> ConversationContext:
        now = datetime.now()
        if self.context_cache and self.context_cache_time:
            if (now - self.context_cache_time).seconds < 300:
                return self.context_cache

        context = ConversationContext(
            user_name="User", user_email="unknown",
            current_date=now.strftime("%Y-%m-%d %H:%M"),
            recent_commits="No recent commits.",
            repo_info="Not in a git repository"
        )

        try:
            name = subprocess.check_output(["git", "config", "--get", "user.name"], text=True, stderr=subprocess.DEVNULL).strip()
            email = subprocess.check_output(["git", "config", "--get", "user.email"], text=True, stderr=subprocess.DEVNULL).strip()
            context.user_name = name
            context.user_email = email

            try:
                repo = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL).strip()
                repo_name = repo.split('/')[-1]
                branch = subprocess.check_output(["git", "branch", "--show-current"], text=True, stderr=subprocess.DEVNULL).strip()
                context.repo_info = f"Repo: {repo_name} (branch: {branch})"
            except:
                pass

            commits = subprocess.check_output(["git", "log", "-n", "25", "--pretty=format:%h | %s | %ar"], text=True, stderr=subprocess.DEVNULL).strip()
            if commits:
                context.recent_commits = f"Recent commits:\n{commits}"
        except:
            pass

        self.context_cache = context
        self.context_cache_time = now
        return context

    async def _classify_intent(self, user_message: str) -> Intent:
        context = self._get_context()
        prompt = f"""Classify intent. Output ONLY the category name.

User: {context.user_name}
Message: "{user_message}"

Categories:
FACTUAL_LOCAL - Questions about their commits/code
FACTUAL_EXTERNAL - Questions about docs/libraries/programming
EVALUATIVE - Quality assessments
HYPOTHETICAL - Design discussions
CHAT - Greetings/chitchat
INVALID - False premises

Output one word:"""

        try:
            classification = await analyze_code(prompt=prompt, code="", language="text", stream=False, temperature=0.0, stop=["\n"])
            intent_str = classification.strip().upper()
            intent_map = {
                "FACTUAL_LOCAL": Intent.FACTUAL_LOCAL,
                "FACTUAL_EXTERNAL": Intent.FACTUAL_EXTERNAL,
                "EVALUATIVE": Intent.EVALUATIVE,
                "HYPOTHETICAL": Intent.HYPOTHETICAL,
                "CHAT": Intent.CHAT,
                "INVALID": Intent.INVALID,
            }
            return intent_map.get(intent_str, Intent.CHAT)
        except:
            return Intent.CHAT

    async def _execute_tool(self, decision: ToolDecision) -> Dict[str, Any]:
        """Execute tool based on router decision"""
        try:
            if decision.tool == ToolType.SEARCH_COMMITS:
                # Use smart_search which already handles repo filtering
                search_result = await asyncio.to_thread(
                    smart_search,
                    query=decision.query,
                    limit=15
                )

                # If router provided filters, apply them manually
                results = search_result.get('results', [])

                if decision.repo_filter:
                    results = [r for r in results if decision.repo_filter.lower() in r.get('repo', '').lower()]

                if decision.language_filter:
                    results = [r for r in results if any(
                        f.get('language', '').lower() == decision.language_filter.lower()
                        for f in r.get('files', [])
                    )]

                # Format for display
                formatted = []
                for commit in results[:10]:
                    formatted.append({
                        "hash": commit.get('commit_hash', 'unknown'),
                        "message": commit.get('message', 'No message'),
                        "date": commit.get('date', 'unknown'),
                        "repo": commit.get('repo', 'unknown'),
                        "files": [f.get('path', '') for f in commit.get('files', [])[:3]],
                        "snippets": commit.get('code_snippets', [])[:1],
                        "score": commit.get('score', 0.0),
                        "match_type": commit.get('match_type', 'unknown')
                    })

                return {
                    "tool": "search_commits",
                    "query": decision.query,
                    "filters": {
                        "repo": decision.repo_filter,
                        "language": decision.language_filter
                    },
                    "count": len(formatted),
                    "results": formatted,
                    "reasoning": decision.reasoning
                }

            elif decision.tool == ToolType.WEB_SEARCH:
                results = await asyncio.to_thread(
                    self.web.search,
                    query=decision.query,
                    num_results=5
                )

                formatted = []
                for result in results[:5]:
                    formatted.append({
                        "title": result.get('title', 'No title')[:100],
                        "url": result.get('url', ''),
                        "snippet": result.get('snippet', '')[:200],
                        "source": result.get('source', 'unknown')
                    })

                return {
                    "tool": "web_search",
                    "query": decision.query,
                    "count": len(formatted),
                    "results": formatted
                }
        except Exception as e:
            return {"tool": decision.tool.value, "error": str(e), "count": 0, "results": []}
        return {"error": "Unknown tool"}

    def _build_system_prompt(self, intent: Intent, context: ConversationContext) -> str:
        base = f"You are DevLog, a CLI coding assistant.\nUser: {context.user_name} ({context.user_email})\nDate: {context.current_date}\n{context.repo_info}\n\n"

        if intent == Intent.EVALUATIVE:
            return base + "User asks for evaluation. State you need specific criteria. Offer to check specific parts."
        elif intent == Intent.INVALID:
            return base + "User's premise is incorrect. Politely correct them based on actual commit history."
        elif intent == Intent.HYPOTHETICAL:
            return base + "Answer hypothetical with general software principles. State assumptions."
        else:
            return base + "Answer clearly and concisely using the tool results. Be specific with commit hashes, file names, and dates. Don't mention using tools."

    def _format_history(self) -> str:
        lines = []
        for msg in self.history[-self.max_history:]:
            if msg.role == "user":
                lines.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                lines.append(f"Assistant: {msg.content}")
        return "\n".join(lines) if lines else ""

    def _format_tool_result(self, tool_result: Dict[str, Any]) -> str:
        if tool_result.get('error'):
            return f"Tool error: {tool_result['error']}"

        lines = [f"\n[Tool: {tool_result['tool']} | Found: {tool_result['count']} results]"]

        if tool_result.get('filters'):
            filters = tool_result['filters']
            if filters.get('repo'):
                lines.append(f"  Filtered by repo: '{filters['repo']}'")
            if filters.get('language'):
                lines.append(f"  Filtered by language: '{filters['language']}'")

        if tool_result['tool'] == 'search_commits':
            lines.append("\nCommits found:")
            for r in tool_result['results'][:5]:
                lines.append(f"  {r['hash']} | {r['message'][:80]} | {r['date']} | {r['repo']}")
                if r['files']:
                    lines.append(f"    Files: {', '.join(r['files'])}")
                if r.get('snippets') and r['snippets'][0]:
                    snippet = r['snippets'][0][:150].replace('\n', ' ')
                    lines.append(f"    Code: {snippet}...")
                lines.append(f"    Match: {r.get('match_type', 'unknown')} (score: {r.get('score', 0):.2f})")

        elif tool_result['tool'] == 'web_search':
            lines.append("\nWeb results:")
            for r in tool_result['results'][:3]:
                lines.append(f"  {r['title']}")
                lines.append(f"  {r['snippet'][:100]}...")

        return "\n".join(lines)

    async def _generate_answer(self, user_message: str, intent: Intent, tool_result: Optional[Dict[str, Any]] = None) -> AsyncGenerator[str, None]:
        context = self._get_context()
        system_prompt = self._build_system_prompt(intent, context)
        history_text = self._format_history()
        tool_context = self._format_tool_result(tool_result) if tool_result else ""

        full_prompt = f"""{system_prompt}

{context.recent_commits[:800]}

{history_text}

{tool_context}

User: {user_message}
Assistant:"""

        try:
            response = await analyze_code(prompt=full_prompt, code="", language="text", stream=True, temperature=0.7)
            async for chunk in response:
                yield chunk
        except Exception as e:
            yield f"Error: {str(e)}"

    async def send_message(self, user_message: str) -> AsyncGenerator[str, None]:
        self.history.append(Message(role="user", content=user_message))

        # Step 1: Classify intent
        intent = await self._classify_intent(user_message)

        # Step 2: Route to tool using smart router
        decision = self.router.route(user_message, intent)

        tool_result = None
        if decision.tool != ToolType.NONE:
            yield f"[{decision.reasoning}]\n"

            tool_result = await self._execute_tool(decision)

            if tool_result.get('count', 0) > 0:
                yield f"[Found {tool_result['count']} results]\n"
            else:
                yield f"[No results found]\n"

            self.history.append(Message(role="tool", content=str(tool_result), tool_name=decision.tool.value))

        # Step 3: Generate final answer
        full_answer = ""
        async for chunk in self._generate_answer(user_message, intent, tool_result):
            full_answer += chunk
            yield chunk

        self.history.append(Message(role="assistant", content=full_answer))

    def get_history(self) -> List[Message]:
        return self.history

    def clear_history(self):
        self.history.clear()
