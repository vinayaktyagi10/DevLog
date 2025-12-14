import json
import ast
import asyncio
from typing import Dict, Any, Optional, AsyncGenerator, List

import jsonschema

from devlog.analysis.llm import analyze_code, LLMConfig
from devlog.core.search import search_commits as keyword_search_commits
from devlog.search.web_search import WebSearcher


# ----------------------------
# Tool schema (strict)
# ----------------------------

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {"type": ["string", "null"]},
        "args": {"type": "object"}
    },
    "required": ["tool"]
}


# ----------------------------
# Robust JSON extraction
# ----------------------------

def extract_first_object(text: str) -> Optional[str]:
    stack = []
    start = None

    for i, ch in enumerate(text):
        if ch == "{":
            if start is None:
                start = i
            stack.append("{")
        elif ch == "}" and stack:
            stack.pop()
            if not stack and start is not None:
                return text[start:i + 1]
    return None


def parse_tool_call(raw: str) -> Optional[Dict[str, Any]]:
    candidate = extract_first_object(raw)
    if not candidate:
        return None

    # JSON first
    try:
        data = json.loads(candidate)
        jsonschema.validate(instance=data, schema=TOOL_SCHEMA)
        return data
    except Exception:
        pass

    # Python literal fallback (single quotes)
    try:
        data = ast.literal_eval(candidate)
        if isinstance(data, dict):
            jsonschema.validate(instance=data, schema=TOOL_SCHEMA)
            return data
    except Exception:
        pass

    return None


# ----------------------------
# ChatManager (rewritten)
# ----------------------------

class ChatManager:
    def __init__(self, model: str = LLMConfig.MODEL):
        self.model = model
        self.history: List[Dict[str, str]] = []
        self.web = WebSearcher()

    def _get_user_context(self) -> Dict:
        """Retrieve user name, email, and recent commit summary."""
        import subprocess
        
        context = {"name": "User", "email": "unknown", "recent_commits": "No recent commits found."}
        
        try:
            name = subprocess.check_output(["git", "config", "--get", "user.name"], text=True).strip()
            email = subprocess.check_output(["git", "config", "--get", "user.email"], text=True).strip()
            context["name"] = name
            context["email"] = email
            
            # Get recent commit summary (increased to 25 for better context)
            commits = subprocess.check_output(["git", "log", "-n", "25", "--oneline"], text=True).strip()
            if commits:
                context["recent_commits"] = f"Recent 25 commits:\n{commits}"
                
        except Exception:
            pass
            
        return context

    # -------- SYSTEM PROMPTS --------

    def _decision_prompt(self, user_message: str) -> str:
        user_context = self._get_user_context()
        
        return (
            "You are a routing engine for a local DevLog AI assistant. "
            f"You are assisting {user_context['name']} ({user_context['email']}). "
            "Your organization is SDC.\n"
            "Decide if a tool is required to answer the user's message.\n\n"
            "Output ONLY a JSON object in this form:\n"
            '{ "tool": "search_commits" | "web_search" | null, "args": {...} }\n\n'
            "Rules:\n"
            "- No explanation\n"
            "- No reasoning\n"
            "- No markdown\n"
            "- Use double quotes for JSON\n\n"
            f"User message:\n{user_message}\n\n"
            f"Context:\n{user_context['recent_commits']}"
        )

    def _final_system_prompt(self) -> str:
        user_context = self._get_user_context()
        return (
            "You are DevLog, a local CLI coding assistant.\n"
            f"User: {user_context['name']} ({user_context['email']}). Org: SDC.\n"
            "Answer clearly and concisely using the provided context.\n"
            "Do NOT reveal internal reasoning.\n"
            "Do NOT explicitly mention tool usage (e.g., 'I used the tool...'). Just give the answer.\n"
        )

    # -------- TOOL DECISION --------

    async def _decide_tool(self, user_message: str) -> Optional[Dict[str, Any]]:
        raw = await analyze_code(
            prompt=self._decision_prompt(user_message),
            code="",
            language="json",
            stream=False,
            temperature=0.0,
            stop=["\n\n"]
        )

        return parse_tool_call(raw)

    # -------- TOOL EXECUTION --------

    async def _run_tool(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool == "search_commits":
            results = await asyncio.to_thread(
                keyword_search_commits,
                query=args.get("query", ""),
                limit=args.get("limit", 10)
            )
            # Enrich commit data
            enriched_results = []
            for commit in results:
                enriched_results.append({
                    "short_hash": commit['short_hash'],
                    "message": commit['message'],
                    "repo_name": commit['repo_name'],
                    "author": commit.get('author', 'unknown'),
                    "date": commit.get('timestamp', 'unknown'),
                    "files_changed": [{"file_path": f['file_path'], "change_type": f['change_type']} for f in commit.get('files', [])[:3]]
                })
            return {"tool": tool, "results": enriched_results}

        if tool == "web_search":
            results = await asyncio.to_thread(
                self.web.search,
                query=args.get("query", ""),
                num_results=args.get("limit", 3)
            )
            return {"tool": tool, "results": results}

        return {"error": f"Unknown tool: {tool}"}

    # -------- FINAL ANSWER --------

    async def _stream_final_answer(self) -> AsyncGenerator[str, None]:
        # Construct a string prompt from history
        prompt_parts = [self._final_system_prompt()]
        
        for msg in self.history:
            if msg["role"] == "user":
                prompt_parts.append(f"\n[USER]: {msg['content']}")
            elif msg["role"] == "assistant":
                prompt_parts.append(f"\n[ASSISTANT]: {msg['content']}")
            elif msg["role"] == "tool":
                prompt_parts.append(f"\n[TOOL RESULT]: {msg['content']}")
        
        prompt_parts.append("\n[ASSISTANT]:")
        final_prompt = "\n".join(prompt_parts)

        response = await analyze_code(
            prompt=final_prompt,
            code="",
            language="text",
            stream=True,
            temperature=0.7 # Higher temp for natural language
        )

        async for chunk in response:
            yield chunk

    # -------- PUBLIC ENTRY POINT --------

    async def _classify_intent(self, user_message: str) -> str:
        """
        Classify user intent to guide tool usage and answer framing.
        Categories:
        - FACTUAL_LOCAL: Questions about specific code, commits, errors in this repo. (Needs tool)
        - FACTUAL_EXTERNAL: Questions about general docs, libraries, news. (Needs web tool)
        - EVALUATIVE: High-level quality/architecture/readiness questions. (No tool default)
        - HYPOTHETICAL: "What if" scenarios or assumptions. (No tool default)
        - INVALID: Premise contradicts reality (e.g. "assume Django" when not), or nonsensical. (Refuse)
        - CHAT: General greeting/chitchat. (No tool)
        """
        prompt = (
            f"Classify the intent of this user message into exactly one category.\n"
            f"User message: \"{user_message}\"\n\n"
            "Categories:\n"
            "FACTUAL_LOCAL: Asking about specific commits, files, errors, or 'what did I do'.\n"
            "FACTUAL_EXTERNAL: Asking about docs, libraries, news, 'latest version', 'how to'.\n"
            "EVALUATIVE: Asking 'is it good?', 'production ready?', 'architecture review'.\n"
            "HYPOTHETICAL: Asking 'what if', 'assume X', 'design a system'.\n"
            "INVALID: Asking based on false premise (e.g. 'assume Django' when irrelevant), or malicious.\n"
            "CHAT: 'Hello', 'thanks', 'who are you'.\n\n"
            "Output ONLY the category name."
        )
        
        raw_classification = await analyze_code(
            prompt=prompt,
            code="",
            language="text",
            stream=False,
            temperature=0.0,
            stop=["\n"]
        )
        
        intent = raw_classification.strip().upper()
        # Fallback to CHAT if model hallucinates a category
        valid_intents = {"FACTUAL_LOCAL", "FACTUAL_EXTERNAL", "EVALUATIVE", "HYPOTHETICAL", "INVALID", "CHAT"}
        if intent not in valid_intents:
            return "CHAT"
        return intent

    async def send_message(self, user_message: str) -> AsyncGenerator[str, None]:
        # Record user input
        self.history.append({"role": "user", "content": user_message})

        # --- PHASE 0: Classify Intent ---
        intent = await self._classify_intent(user_message)
        # yield f"[Intent detected: {intent}]\n" # Debugging visibility

        tool_name = None
        tool_args = {}
        
        # --- PHASE 1 & 2: Tool Routing (Only for Factual Intents) ---
        if intent in ["FACTUAL_LOCAL", "FACTUAL_EXTERNAL"]:
            decision = await self._decide_tool(user_message)
            tool_name = decision.get("tool") if decision else None
            tool_args = decision.get("args", {}) if decision else {}

            if tool_name:
                yield f"[Running tool: {tool_name} with args: {tool_args} ...]\n"
                try:
                    tool_result = await self._run_tool(tool_name, tool_args)
                    tool_result_content = json.dumps(tool_result)
                    
                    # Add tool result to history
                    self.history.append({
                        "role": "tool", 
                        "content": tool_result_content,
                        "name": tool_name # Helper for prompt building
                    })
                except Exception as e:
                    yield f"[Error: {e}]"
                    self.history.append({"role": "system", "content": f"Tool execution failed: {e}"})
        
        # --- PHASE 3: Final Answer ---
        # Construct specific prompt based on intent
        user_context_final_answer = self._get_user_context()
        base_system_prompt = (
            "You are DevLog, a local CLI coding assistant.\n"
            f"User: {user_context_final_answer['name']} ({user_context_final_answer['email']}). Org: SDC.\n"
        )

        if intent == "EVALUATIVE":
            system_content_final_answer = base_system_prompt + (
                "The user is asking for an evaluation. Do NOT guess.\n"
                "State clearly that you cannot judge conclusively without specific criteria.\n"
                "List specific criteria (e.g. tests, security, docs) needed for a proper evaluation.\n"
                "Offer to check specific parts of the codebase if they provide them."
            )
        elif intent == "INVALID":
            system_content_final_answer = base_system_prompt + (
                "The user's premise seems incorrect or contradicts known context (e.g. asking about Django if not present).\n"
                "Politely REFUSE to answer based on the false premise.\n"
                "Correct the premise based on what you know about the repo (from recent commits context).\n"
                "Do NOT try to be helpful by hallucinating an answer to a false premise."
            )
        elif intent == "HYPOTHETICAL":
             system_content_final_answer = base_system_prompt + (
                "The user is asking a hypothetical question.\n"
                "Answer based on general software engineering principles.\n"
                "Clearly state any assumptions you make."
            )
        else:
            # Standard/Factual/Chat
            system_content_final_answer = base_system_prompt + (
                "Answer clearly and concisely using the provided context and tool results.\n"
                "Do NOT reveal internal reasoning.\n"
                "Do NOT explicitly mention tool usage."
            )
        
        # Build prompt string for final answer
        final_answer_prompt_parts = [system_content_final_answer]
        for msg in self.history:
            if msg["role"] == "user":
                final_answer_prompt_parts.append(f"\n[USER]: {msg['content']}")
            elif msg["role"] == "assistant":
                final_answer_prompt_parts.append(f"\n[ASSISTANT]: {msg['content']}")
            elif msg["role"] == "tool":
                final_answer_prompt_parts.append(f"\n[TOOL RESULT ({msg.get('name', 'unknown')})]: {msg['content']}")
        final_answer_prompt_parts.append("\n[ASSISTANT]:")
        
        final_answer_prompt = "\n".join(final_answer_prompt_parts)

        response_generator = await analyze_code(
            prompt=final_answer_prompt,
            code="", # Corrected from None
            language="text",
            stream=True,
            temperature=0.7,
            stop=[]
        )
        
        full_answer_content = ""
        async for chunk in response_generator:
            full_answer_content += chunk
            yield chunk
        
        self.history.append({"role": "assistant", "content": full_answer_content})


    def get_history(self) -> List[Dict]:
        return self.history

    def clear_history(self):
        self.history.clear()