"""
Enhanced Chat Manager - Complete rewrite with tool system and workflows
"""

import asyncio
import subprocess
import re
from typing import Optional, AsyncGenerator, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from devlog.analysis.llm import analyze_code, LLMConfig
from devlog.analysis.tool_registry import get_tool_registry, ToolRegistry
from devlog.analysis.smart_router import SmartToolRouter, RoutingDecision


@dataclass
class ConversationContext:
    """Conversation context"""
    user_name: str
    user_email: str
    current_date: str
    recent_commits: str
    repo_info: str
    current_repo: Optional[str] = None
    current_branch: Optional[str] = None


@dataclass
class Message:
    """Chat message"""
    role: str  # user/assistant/tool/system
    content: str
    tool_name: Optional[str] = None
    tool_result: Optional[Dict] = None
    timestamp: Optional[str] = None


class WorkflowStep(Enum):
    """Multi-step workflow steps"""
    SEARCH = "search"
    ANALYZE = "analyze"
    COMPARE = "compare"
    SYNTHESIZE = "synthesize"


@dataclass
class Workflow:
    """Multi-step workflow"""
    name: str
    steps: List[WorkflowStep]
    current_step: int = 0
    results: Dict[str, Any] = None

    def __post_init__(self):
        if self.results is None:
            self.results = {}


class EnhancedChatManager:
    """Enhanced chat manager with tool system and workflows"""

    def __init__(self, model: str = LLMConfig.MODEL):
        self.model = model
        self.history: List[Message] = []
        self.tool_registry: ToolRegistry = get_tool_registry()
        self.router = SmartToolRouter()
        self.max_history = 10  # Keep last 10 messages
        self.context_cache: Optional[ConversationContext] = None
        self.context_cache_time: Optional[datetime] = None
        self.current_workflow: Optional[Workflow] = None
        self.current_conversation_id: Optional[int] = None

        # Slash command handlers
        self.slash_commands = {
            '/help': self._cmd_help,
            '/search': self._cmd_search,
            '/analyze': self._cmd_analyze,
            '/review': self._cmd_review,
            '/stats': self._cmd_stats,
            '/repos': self._cmd_repos,
            '/compare': self._cmd_compare,
            '/export': self._cmd_export,
            '/clear': self._cmd_clear,
            '/history': self._cmd_history,
        }

    def _get_context(self) -> ConversationContext:
        """Get or refresh context"""
        now = datetime.now()
        if self.context_cache and self.context_cache_time:
            if (now - self.context_cache_time).seconds < 300:  # 5 min cache
                return self.context_cache

        context = ConversationContext(
            user_name="User",
            user_email="unknown",
            current_date=now.strftime("%Y-%m-%d %H:%M"),
            recent_commits="No recent commits.",
            repo_info="Not in a git repository"
        )

        try:
            # Get git user
            name = subprocess.check_output(
                ["git", "config", "--get", "user.name"],
                text=True,
                stderr=subprocess.DEVNULL
            ).strip()
            email = subprocess.check_output(
                ["git", "config", "--get", "user.email"],
                text=True,
                stderr=subprocess.DEVNULL
            ).strip()
            context.user_name = name
            context.user_email = email

            # Get repo info
            try:
                repo = subprocess.check_output(
                    ["git", "rev-parse", "--show-toplevel"],
                    text=True,
                    stderr=subprocess.DEVNULL
                ).strip()
                repo_name = repo.split('/')[-1]
                branch = subprocess.check_output(
                    ["git", "branch", "--show-current"],
                    text=True,
                    stderr=subprocess.DEVNULL
                ).strip()
                context.repo_info = f"Repo: {repo_name} (branch: {branch})"
                context.current_repo = repo_name
                context.current_branch = branch
            except:
                pass

            # Get recent commits (last 25)
            commits = subprocess.check_output(
                ["git", "log", "-n", "25", "--pretty=format:%h | %s | %ar"],
                text=True,
                stderr=subprocess.DEVNULL
            ).strip()
            if commits:
                context.recent_commits = f"Recent commits:\n{commits}"
        except:
            pass

        self.context_cache = context
        self.context_cache_time = now
        return context

    async def send_message(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        Send message and get streaming response

        Handles:
        1. Slash commands
        2. Tool routing
        3. Multi-step workflows
        4. Natural conversation
        """
        # Add user message to history
        self.history.append(Message(
            role="user",
            content=user_message,
            timestamp=datetime.now().isoformat()
        ))

        # Check for slash command
        if user_message.startswith('/'):
            async for chunk in self._handle_slash_command(user_message):
                yield chunk
            return

        # Check if continuing a workflow
        if self.current_workflow:
            async for chunk in self._continue_workflow(user_message):
                yield chunk
            return

        # Route to appropriate handler
        context = self._get_context()
        routing = await self.router.route(user_message, {
            'current_repo': context.current_repo,
            'current_branch': context.current_branch
        })

        # Log routing decision
        yield f"[Routing: {routing.tool_name} ({routing.confidence:.2f})]\n"

        # Execute tool if needed
        tool_result = None
        if routing.tool_name != 'none':
            # Check for workflows
            workflow = self._detect_workflow(routing)
            if workflow:
                self.current_workflow = workflow
                async for chunk in self._execute_workflow():
                    yield chunk
                return

            # Single tool execution
            yield f"[Using tool: {routing.tool_name}]\n"

            try:
                # Inject conversation_id
                if self.current_conversation_id:
                    routing.parameters['conversation_id'] = self.current_conversation_id

                tool_result = await self.tool_registry.execute_tool(
                    routing.tool_name,
                    **routing.parameters
                )

                # Add tool result to history
                self.history.append(Message(
                    role="tool",
                    content=str(tool_result),
                    tool_name=routing.tool_name,
                    tool_result=tool_result,
                    timestamp=datetime.now().isoformat()
                ))

                # Show result summary
                result_summary = self._format_tool_result_summary(tool_result)
                yield f"{result_summary}\n"

            except Exception as e:
                yield f"[Tool error: {e}]\n"

        # Generate natural language response
        async for chunk in self._generate_response(user_message, tool_result, routing):
            yield chunk

    def _detect_workflow(self, routing: RoutingDecision) -> Optional[Workflow]:
        """Detect if query requires multi-step workflow"""

        # Review workflow: search -> analyze -> compare -> synthesize
        if routing.tool_name == 'start_review':
            return Workflow(
                name="code_review",
                steps=[
                    WorkflowStep.SEARCH,
                    WorkflowStep.ANALYZE,
                    WorkflowStep.COMPARE,
                    WorkflowStep.SYNTHESIZE
                ]
            )

        # Complex analysis: search -> analyze -> synthesize
        if routing.tool_name == 'analyze_commit' and routing.parameters.get('commit_hash') == 'NEEDS_SEARCH':
            return Workflow(
                name="search_and_analyze",
                steps=[
                    WorkflowStep.SEARCH,
                    WorkflowStep.ANALYZE,
                    WorkflowStep.SYNTHESIZE
                ]
            )

        return None

    async def _execute_workflow(self) -> AsyncGenerator[str, None]:
        """Execute multi-step workflow"""
        workflow = self.current_workflow

        yield f"[Starting workflow: {workflow.name}]\n"

        for step in workflow.steps:
            yield f"[Step {workflow.current_step + 1}/{len(workflow.steps)}: {step.value}]\n"

            if step == WorkflowStep.SEARCH:
                # Search for relevant commits
                result = await self.tool_registry.execute_tool('search_commits', query="", limit=10)
                workflow.results['search'] = result
                yield f"Found {result.get('count', 0)} commits\n"

            elif step == WorkflowStep.ANALYZE:
                # Analyze top results
                commits = workflow.results.get('search', {}).get('results', [])
                if commits:
                    top_commit = commits[0]
                    result = await self.tool_registry.execute_tool(
                        'analyze_commit',
                        commit_hash=top_commit.get('commit_hash', '')
                    )
                    workflow.results['analyze'] = result
                    yield f"Analysis complete\n"

            elif step == WorkflowStep.COMPARE:
                # Compare with best practices
                result = await self.tool_registry.execute_tool('web_search', query="best practices", limit=5)
                workflow.results['compare'] = result
                yield f"Comparison complete\n"

            elif step == WorkflowStep.SYNTHESIZE:
                # Synthesize all results
                yield "[Synthesizing results]\n"
                async for chunk in self._synthesize_workflow_results(workflow):
                    yield chunk

            workflow.current_step += 1

        # Clear workflow
        self.current_workflow = None
        yield "\n[Workflow complete]\n"

    async def _continue_workflow(self, user_message: str) -> AsyncGenerator[str, None]:
        """Continue existing workflow based on user input"""
        yield "[Continuing workflow]\n"
        # Implementation depends on workflow state
        async for chunk in self._execute_workflow():
            yield chunk

    async def _synthesize_workflow_results(self, workflow: Workflow) -> AsyncGenerator[str, None]:
        """Synthesize workflow results into coherent response"""

        # Build synthesis prompt
        parts = [f"Synthesize the following workflow results for '{workflow.name}':"]

        for step_name, result in workflow.results.items():
            parts.append(f"\n{step_name.upper()} RESULTS:")
            parts.append(str(result)[:500])  # Limit to avoid context overflow

        parts.append("\nProvide a clear, actionable summary:")

        prompt = "\n".join(parts)

        async for chunk in analyze_code(prompt=prompt, code="", language="text", stream=True):
            yield chunk

    def _format_tool_result_summary(self, result: Dict[str, Any]) -> str:
        """Format tool result for display"""

        tool_name = result.get('tool', 'unknown')

        if 'error' in result:
            return f"❌ {result['error']}"

        if tool_name == 'search_commits':
            count = result.get('count', 0)
            return f"✓ Found {count} commits"

        elif tool_name == 'analyze_commit':
            commit = result.get('commit_hash', 'unknown')
            return f"✓ Analyzed commit {commit}"

        elif tool_name == 'start_review':
            topic = result.get('topic', 'unknown')
            return f"✓ Review started for '{topic}'"

        elif tool_name == 'show_commit':
            return "✓ Commit details retrieved"

        elif tool_name == 'web_search':
            count = result.get('count', 0)
            return f"✓ Found {count} web results"

        return "✓ Tool executed successfully"

    async def _generate_response(
        self,
        user_message: str,
        tool_result: Optional[Dict],
        routing: RoutingDecision
    ) -> AsyncGenerator[str, None]:
        """Generate natural language response"""

        context = self._get_context()

        # Build prompt
        prompt_parts = [
            f"You are DevLog, an AI coding assistant.",
            f"User: {context.user_name} ({context.user_email})",
            f"Date: {context.current_date}",
            f"{context.repo_info}",
            ""
        ]

        # Add conversation history (last few messages)
        for msg in self.history[-self.max_history:]:
            if msg.role == "user":
                prompt_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                prompt_parts.append(f"Assistant: {msg.content[:200]}")  # Truncate

        # Add tool result if available
        if tool_result:
            prompt_parts.append("\nTool Result:")
            prompt_parts.append(self._format_tool_result_for_llm(tool_result))

        # Add current query
        prompt_parts.append(f"\nUser: {user_message}")
        prompt_parts.append("Assistant:")

        full_prompt = "\n".join(prompt_parts)

        # Stream response
        full_response = ""
        try:
            async for chunk in analyze_code(
                prompt=full_prompt,
                code="",
                language="text",
                stream=True,
                temperature=0.7
            ):
                full_response += chunk
                yield chunk
        except Exception as e:
            yield f"\n[Error generating response: {e}]"
            full_response = f"Error: {e}"

        # Add to history
        self.history.append(Message(
            role="assistant",
            content=full_response,
            timestamp=datetime.now().isoformat()
        ))

    def _format_tool_result_for_llm(self, result: Dict[str, Any]) -> str:
        """Format tool result for LLM consumption"""

        tool_name = result.get('tool', 'unknown')

        if tool_name == 'search_commits':
            lines = [f"Found {result.get('count', 0)} commits:"]
            for r in result.get('results', [])[:5]:
                lines.append(f"- {r.get('commit_hash', 'unknown')}: {r.get('message', 'No message')[:80]}")
                lines.append(f"  Repo: {r.get('repo', 'unknown')}, Date: {r.get('date', 'unknown')}")
            return "\n".join(lines)

        elif tool_name == 'analyze_commit':
            analysis = result.get('result', {})
            lines = [f"Analysis of commit {result.get('commit_hash', 'unknown')}:"]

            if analysis.get('summary'):
                lines.append(f"Summary: {analysis['summary']}")

            if analysis.get('issues'):
                lines.append(f"\nIssues ({len(analysis['issues'])}):")
                for issue in analysis['issues'][:5]:
                    lines.append(f"- {issue}")

            if analysis.get('suggestions'):
                lines.append(f"\nSuggestions ({len(analysis['suggestions'])}):")
                for sug in analysis['suggestions'][:5]:
                    lines.append(f"- {sug}")

            return "\n".join(lines)

        elif tool_name == 'show_stats':
            return f"""Statistics:
- Total commits: {result.get('total_commits', 0)}
- Lines added: {result.get('insertions', 0)}
- Lines deleted: {result.get('deletions', 0)}
- Top repos: {', '.join([r[0] for r in result.get('top_repos', [])[:3]])}"""

        # Generic formatting
        return str(result)[:500]

    # ==================== SLASH COMMANDS ====================

    async def _handle_slash_command(self, message: str) -> AsyncGenerator[str, None]:
        """Handle slash commands"""

        parts = message.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handler = self.slash_commands.get(command)

        if not handler:
            yield f"Unknown command: {command}\n"
            yield "Try /help for available commands\n"
            return

        try:
            async for chunk in handler(args):
                yield chunk
        except Exception as e:
            yield f"Command error: {e}\n"

    async def _cmd_help(self, args: str) -> AsyncGenerator[str, None]:
        """Show help"""
        help_text = self.tool_registry.get_help_text()

        yield "\n# Slash Commands\n\n"
        yield "/help - Show this help\n"
        yield "/search <query> - Search commits\n"
        yield "/analyze <hash> - Analyze commit\n"
        yield "/review <topic> - Start code review\n"
        yield "/stats - Show statistics\n"
        yield "/repos - List repositories\n"
        yield "/compare <hash1,hash2> - Compare commits\n"
        yield "/export [format] - Export conversation\n"
        yield "/clear - Clear chat history\n"
        yield "/history - Show conversation history\n"
        yield "\n" + help_text

    async def _cmd_search(self, args: str) -> AsyncGenerator[str, None]:
        """Search commits"""
        result = await self.tool_registry.execute_tool('search_commits', query=args, limit=10)
        yield self._format_tool_result_summary(result) + "\n"
        yield self._format_tool_result_for_llm(result) + "\n"

    async def _cmd_analyze(self, args: str) -> AsyncGenerator[str, None]:
        """Analyze commit"""
        result = await self.tool_registry.execute_tool('analyze_commit', commit_hash=args)
        yield self._format_tool_result_summary(result) + "\n"
        yield self._format_tool_result_for_llm(result) + "\n"

    async def _cmd_review(self, args: str) -> AsyncGenerator[str, None]:
        """Start review"""
        result = await self.tool_registry.execute_tool('start_review', topic=args)
        yield self._format_tool_result_summary(result) + "\n"

    async def _cmd_stats(self, args: str) -> AsyncGenerator[str, None]:
        """Show stats"""
        result = await self.tool_registry.execute_tool('show_stats')
        yield self._format_tool_result_for_llm(result) + "\n"

    async def _cmd_repos(self, args: str) -> AsyncGenerator[str, None]:
        """List repos"""
        result = await self.tool_registry.execute_tool('list_repos')
        yield f"Found {result.get('count', 0)} repositories:\n"
        for repo in result.get('repos', []):
            active = "✓" if repo.get('active') else "○"
            yield f"{active} {repo.get('repo_name')} ({repo.get('commit_count', 0)} commits)\n"

    async def _cmd_compare(self, args: str) -> AsyncGenerator[str, None]:
        """Compare commits"""
        result = await self.tool_registry.execute_tool('compare_commits', commit_hashes=args)
        yield "Comparison results:\n"
        yield str(result) + "\n"

    async def _cmd_export(self, args: str) -> AsyncGenerator[str, None]:
        """Export conversation"""
        format_type = args.strip() or 'markdown'
        params = {'format': format_type}
        if self.current_conversation_id:
            params['conversation_id'] = self.current_conversation_id

        result = await self.tool_registry.execute_tool('export_conversation', **params)
        yield str(result.get('message', 'Export complete')) + "\n"

    async def _cmd_clear(self, args: str) -> AsyncGenerator[str, None]:
        """Clear history"""
        self.history.clear()
        self.current_workflow = None
        yield "Chat history cleared\n"

    async def _cmd_history(self, args: str) -> AsyncGenerator[str, None]:
        """Show history"""
        yield f"Conversation history ({len(self.history)} messages):\n\n"
        for i, msg in enumerate(self.history, 1):
            role_emoji = "👤" if msg.role == "user" else "🤖" if msg.role == "assistant" else "🔧"
            yield f"{i}. {role_emoji} [{msg.role}] {msg.content[:80]}...\n"

    # ==================== UTILITY ====================

    def get_history(self) -> List[Message]:
        """Get conversation history"""
        return self.history

    def repopulate_history(self, messages: List[Dict[str, Any]]):
        """Repopulate history from persisted messages"""
        self.history = []
        for msg in messages:
            self.history.append(Message(
                role=msg['role'],
                content=msg['content'],
                tool_name=msg.get('tool_name'),
                tool_result=msg.get('tool_result'),
                timestamp=msg.get('timestamp')
            ))

    def clear_history(self):
        """Clear conversation history"""
        self.history.clear()
        self.current_workflow = None
