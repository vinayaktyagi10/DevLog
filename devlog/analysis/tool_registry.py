"""
Enhanced Tool System - Comprehensive tool registry for chat
"""

from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass
from enum import Enum
import asyncio
from datetime import datetime

from devlog.core.search_unified import smart_search
from devlog.core.search import get_commit_details
from devlog.analysis.analyzer import CodeAnalyzer
from devlog.analysis.review import ReviewPipeline
from devlog.search.web_search import WebSearcher
from devlog.core.embeddings import semantic_search


class ToolCategory(Enum):
    """Tool categories for organization"""
    SEARCH = "search"
    ANALYSIS = "analysis"
    REVIEW = "review"
    DISPLAY = "display"
    UTILITY = "utility"


@dataclass
class ToolDefinition:
    """Definition of a tool"""
    name: str
    category: ToolCategory
    description: str
    parameters: Dict[str, Any]
    handler: Callable
    requires_llm: bool = False
    is_async: bool = True


class ToolRegistry:
    """Registry of all available tools"""

    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self._register_all_tools()

    def _register_all_tools(self):
        """Register all available tools"""

        # SEARCH TOOLS
        self.register(ToolDefinition(
            name="search_commits",
            category=ToolCategory.SEARCH,
            description="Search through your commit history using keywords, natural language, or code content",
            parameters={
                "query": "Search query (keywords or natural language)",
                "repo": "Repository filter (optional)",
                "language": "Programming language filter (optional)",
                "limit": "Max results (default: 15)"
            },
            handler=self._tool_search_commits
        ))

        self.register(ToolDefinition(
            name="semantic_search",
            category=ToolCategory.SEARCH,
            description="Find commits by meaning/concept rather than exact keywords",
            parameters={
                "query": "Concept or description to search for",
                "limit": "Max results (default: 10)"
            },
            handler=self._tool_semantic_search
        ))

        self.register(ToolDefinition(
            name="web_search",
            category=ToolCategory.SEARCH,
            description="Search the web for technical documentation and best practices",
            parameters={
                "query": "Search query",
                "limit": "Max results (default: 10)"
            },
            handler=self._tool_web_search
        ))

        # DISPLAY TOOLS
        self.register(ToolDefinition(
            name="show_commit",
            category=ToolCategory.DISPLAY,
            description="Show detailed information about a specific commit",
            parameters={
                "commit_hash": "Commit hash (short or full)"
            },
            handler=self._tool_show_commit
        ))

        self.register(ToolDefinition(
            name="show_stats",
            category=ToolCategory.DISPLAY,
            description="Show coding statistics and activity summary",
            parameters={},
            handler=self._tool_show_stats
        ))

        # ANALYSIS TOOLS
        self.register(ToolDefinition(
            name="analyze_commit",
            category=ToolCategory.ANALYSIS,
            description="Analyze a commit for issues, suggestions, and code quality",
            parameters={
                "commit_hash": "Commit hash to analyze",
                "analysis_type": "Type: 'quick', 'deep', or 'patterns' (default: quick)",
                "include_context": "Include web best practices in analysis (default: false)"
            },
            handler=self._tool_analyze_commit,
            requires_llm=True
        ))

        self.register(ToolDefinition(
            name="compare_commits",
            category=ToolCategory.ANALYSIS,
            description="Compare multiple commits to identify trends and patterns",
            parameters={
                "commit_hashes": "List of commit hashes to compare (comma-separated)"
            },
            handler=self._tool_compare_commits
        ))

        # REVIEW TOOLS
        self.register(ToolDefinition(
            name="start_review",
            category=ToolCategory.REVIEW,
            description="Start a comprehensive code review on a topic",
            parameters={
                "topic": "Topic to review (e.g., 'authentication', 'error handling')",
                "language": "Programming language (optional)",
                "num_commits": "Number of commits to analyze (default: 5)",
                "deep": "Use deep analysis (default: false)"
            },
            handler=self._tool_start_review,
            requires_llm=True
        ))

        # UTILITY TOOLS
        self.register(ToolDefinition(
            name="list_repos",
            category=ToolCategory.UTILITY,
            description="List all tracked repositories",
            parameters={},
            handler=self._tool_list_repos
        ))

        self.register(ToolDefinition(
            name="export_conversation",
            category=ToolCategory.UTILITY,
            description="Export current conversation to markdown or JSON",
            parameters={
                "format": "Export format: 'markdown' or 'json' (default: markdown)"
            },
            handler=self._tool_export_conversation
        ))

    def register(self, tool: ToolDefinition):
        """Register a tool"""
        self.tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get tool by name"""
        return self.tools.get(name)

    def list_tools(self, category: Optional[ToolCategory] = None) -> List[ToolDefinition]:
        """List all tools, optionally filtered by category"""
        if category:
            return [t for t in self.tools.values() if t.category == category]
        return list(self.tools.values())

    def get_help_text(self) -> str:
        """Generate help text for all tools"""
        lines = ["# Available Tools\n"]

        for category in ToolCategory:
            tools = self.list_tools(category)
            if not tools:
                continue

            lines.append(f"\n## {category.value.title()}\n")

            for tool in tools:
                lines.append(f"### `{tool.name}`")
                lines.append(f"{tool.description}\n")

                if tool.parameters:
                    lines.append("**Parameters:**")
                    for param, desc in tool.parameters.items():
                        lines.append(f"- `{param}`: {desc}")
                    lines.append("")

                if tool.requires_llm:
                    lines.append("*Requires Ollama*\n")

        return "\n".join(lines)

    # ==================== TOOL HANDLERS ====================

    async def _tool_search_commits(self, **kwargs) -> Dict[str, Any]:
        """Search commits handler"""
        query = kwargs.get('query', '')
        repo = kwargs.get('repo')
        language = kwargs.get('language')
        limit = kwargs.get('limit', 15)

        # Use smart_search from unified interface
        result = await asyncio.to_thread(smart_search, query, limit)

        # Apply additional filters if provided
        results = result.get('results', [])

        if repo:
            results = [r for r in results if repo.lower() in r.get('repo', '').lower()]

        if language:
            results = [r for r in results if any(
                f.get('language', '').lower() == language.lower()
                for f in r.get('files', [])
            )]

        return {
            "tool": "search_commits",
            "query": query,
            "filters": {"repo": repo, "language": language},
            "count": len(results),
            "results": results[:limit]
        }

    async def _tool_semantic_search(self, **kwargs) -> Dict[str, Any]:
        """Semantic search handler"""
        query = kwargs.get('query', '')
        limit = kwargs.get('limit', 10)

        results = await asyncio.to_thread(semantic_search, query, limit)

        return {
            "tool": "semantic_search",
            "query": query,
            "count": len(results),
            "results": results
        }

    async def _tool_web_search(self, **kwargs) -> Dict[str, Any]:
        """Web search handler"""
        query = kwargs.get('query', '')
        limit = kwargs.get('limit', 10)

        searcher = WebSearcher()
        results = await asyncio.to_thread(searcher.search, query, limit)

        return {
            "tool": "web_search",
            "query": query,
            "count": len(results),
            "results": results
        }

    async def _tool_show_commit(self, **kwargs) -> Dict[str, Any]:
        """Show commit details handler"""
        commit_hash = kwargs.get('commit_hash', '')

        details = await asyncio.to_thread(get_commit_details, commit_hash)

        if not details:
            return {
                "tool": "show_commit",
                "error": f"Commit not found: {commit_hash}"
            }

        return {
            "tool": "show_commit",
            "commit": details
        }

    async def _tool_show_stats(self, **kwargs) -> Dict[str, Any]:
        """Show statistics handler"""
        import sqlite3
        from devlog.paths import DB_PATH

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Total commits
        c.execute("SELECT COUNT(*) FROM git_commits")
        total_commits = c.fetchone()[0]

        # Lines changed
        c.execute("SELECT SUM(insertions), SUM(deletions) FROM git_commits")
        insertions, deletions = c.fetchone()

        # Commits by repo
        c.execute("""
            SELECT r.repo_name, COUNT(*) as count
            FROM git_commits c
            JOIN tracked_repos r ON c.repo_id = r.id
            WHERE r.active = 1
            GROUP BY r.repo_name
            ORDER BY count DESC
            LIMIT 5
        """)
        top_repos = c.fetchall()

        # Recent activity
        c.execute("""
            SELECT DATE(timestamp) as date, COUNT(*) as count
            FROM git_commits
            WHERE timestamp >= DATE('now', '-7 days')
            GROUP BY date
            ORDER BY date DESC
        """)
        recent = c.fetchall()

        conn.close()

        return {
            "tool": "show_stats",
            "total_commits": total_commits,
            "insertions": insertions or 0,
            "deletions": deletions or 0,
            "top_repos": top_repos,
            "recent_activity": recent
        }

    async def _tool_analyze_commit(self, **kwargs) -> Dict[str, Any]:
        """Analyze commit handler"""
        commit_hash = kwargs.get('commit_hash', '')
        analysis_type = kwargs.get('analysis_type', 'quick')
        include_context = kwargs.get('include_context', False)

        context = None
        if include_context:
            # Get web best practices as context
            searcher = WebSearcher()
            # Extract topic from commit message
            details = await asyncio.to_thread(get_commit_details, commit_hash)
            if details:
                topic = details.get('message', '')[:50]
                web_results = await asyncio.to_thread(searcher.search, topic, 3)
                context = "\n".join([f"- {r['title']}: {r['snippet'][:100]}"
                                    for r in web_results])

        analyzer = CodeAnalyzer()
        result = await analyzer.analyze_commit(commit_hash, analysis_type, context)

        if not result:
            return {
                "tool": "analyze_commit",
                "error": f"Failed to analyze commit: {commit_hash}"
            }

        return {
            "tool": "analyze_commit",
            "commit_hash": commit_hash,
            "analysis_type": analysis_type,
            "result": result
        }

    async def _tool_compare_commits(self, **kwargs) -> Dict[str, Any]:
        """Compare commits handler"""
        from devlog.analysis.compare_commits import CommitComparer

        commit_hashes = kwargs.get('commit_hashes', '')
        hashes = [h.strip() for h in commit_hashes.split(',')]

        comparer = CommitComparer()
        result = await asyncio.to_thread(comparer.compare_commits, hashes)

        return {
            "tool": "compare_commits",
            "commits": hashes,
            "result": result
        }

    async def _tool_start_review(self, **kwargs) -> Dict[str, Any]:
        """Start review handler"""
        topic = kwargs.get('topic', '')
        language = kwargs.get('language')
        num_commits = kwargs.get('num_commits', 5)
        deep = kwargs.get('deep', False)

        pipeline = ReviewPipeline()
        result = await pipeline.review_topic(topic, language, num_commits, deep)

        return {
            "tool": "start_review",
            "topic": topic,
            "result": result
        }

    async def _tool_list_repos(self, **kwargs) -> Dict[str, Any]:
        """List repos handler"""
        import sqlite3
        from devlog.paths import DB_PATH

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT repo_name, repo_path, tracked_since,
                   last_commit_at, commit_count, active
            FROM tracked_repos
            ORDER BY active DESC, last_commit_at DESC
        """)

        repos = [dict(row) for row in c.fetchall()]
        conn.close()

        return {
            "tool": "list_repos",
            "count": len(repos),
            "repos": repos
        }

    async def _tool_export_conversation(self, **kwargs) -> Dict[str, Any]:
        """Export conversation handler"""
        format_type = kwargs.get('format', 'markdown')
        conversation_id = kwargs.get('conversation_id')

        if not conversation_id:
            return {
                "tool": "export_conversation",
                "error": "No active conversation to export"
            }

        from devlog.analysis.conversation_db import get_conversation_manager
        manager = get_conversation_manager()

        try:
            content = manager.export_conversation(conversation_id, format=format_type)

            # Save to file
            filename = f"devlog_export_{conversation_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{'json' if format_type == 'json' else 'md'}"
            with open(filename, 'w') as f:
                f.write(content)

            return {
                "tool": "export_conversation",
                "format": format_type,
                "message": f"Exported to {filename}",
                "filename": filename
            }
        except Exception as e:
            return {
                "tool": "export_conversation",
                "error": f"Export failed: {str(e)}"
            }

    async def execute_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """Execute a tool by name"""
        tool = self.get_tool(tool_name)

        if not tool:
            return {
                "error": f"Unknown tool: {tool_name}",
                "available_tools": list(self.tools.keys())
            }

        try:
            if tool.is_async:
                return await tool.handler(**kwargs)
            else:
                return await asyncio.to_thread(tool.handler, **kwargs)
        except Exception as e:
            return {
                "tool": tool_name,
                "error": f"Tool execution failed: {str(e)}"
            }


# ==================== GLOBAL REGISTRY ====================

_registry = None

def get_tool_registry() -> ToolRegistry:
    """Get the global tool registry"""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
