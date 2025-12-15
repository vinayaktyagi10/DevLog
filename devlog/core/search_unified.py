"""
Unified Search Interface - Single entry point for all search types

Routes queries to appropriate search methods and formats results consistently
"""

from typing import List, Dict, Optional, Tuple
from devlog.core.deep_search import (
    hybrid_search,
    search_code_content,
    search_function_names,
    semantic_search_commits,
    search_in_repo_pattern
)
from devlog.core.search import search_commits as keyword_search


class UnifiedSearch:
    """Unified interface for all search operations"""

    def __init__(self):
        pass

    def search(
        self,
        query: str,
        search_type: str = "auto",
        repo_filter: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 20
    ) -> Dict:
        """
        Main search interface

        Args:
            query: Search query
            search_type: "auto" (default), "code", "function", "semantic", "keyword"
            repo_filter: Filter by repo name pattern
            language: Filter by language
            limit: Max results

        Returns:
            {
                "query": str,
                "search_type": str,
                "results": List[Dict],
                "count": int,
                "repo_filter": str or None
            }
        """
        # Auto-detect search type if needed
        if search_type == "auto":
            search_type = self._detect_search_type(query)

        # Route to appropriate search method
        if search_type == "code":
            results = search_code_content(query, repo_filter, language, limit)
        elif search_type == "function":
            results = search_function_names(query, repo_filter, language, limit)
        elif search_type == "semantic":
            results = semantic_search_commits(query, repo_filter, limit)
        elif search_type == "keyword":
            results = keyword_search(query, repo_filter, language, limit=limit)
        else:
            # Hybrid (best for most queries)
            results = hybrid_search(query, repo_filter, language, limit)

        return {
            "query": query,
            "search_type": search_type,
            "results": results,
            "count": len(results),
            "repo_filter": repo_filter,
            "language": language
        }

    def _detect_search_type(self, query: str) -> str:
        """
        Auto-detect best search type based on query

        Returns: "hybrid", "code", "function", "semantic", "keyword"
        """
        query_lower = query.lower()
        words = query.split()

        # Function search indicators
        if any(indicator in query_lower for indicator in [
            "function", "class", "method", "def ", "async def"
        ]):
            return "function"

        # Code content search indicators
        if any(indicator in query_lower for indicator in [
            "code", "implementation", "algorithm", "logic"
        ]):
            return "code"

        # Semantic search for natural language
        if len(words) > 4 and not any(c in query for c in ["(", ")", "{", "}"]):
            return "semantic"

        # Default: hybrid (combines all methods)
        return "hybrid"

    def search_with_context(
        self,
        query: str,
        repo_filter: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 10
    ) -> Dict:
        """
        Search and return results with rich context (code snippets, functions)

        Returns results optimized for LLM consumption
        """
        search_result = self.search(query, "auto", repo_filter, language, limit)

        # Enrich results with context
        enriched_results = []
        for result in search_result['results']:
            enriched = {
                "commit_hash": result.get('short_hash', 'unknown'),
                "message": result.get('message', 'No message')[:150],
                "date": result.get('timestamp', 'unknown')[:10],
                "repo": result.get('repo_name', 'unknown'),
                "match_type": result.get('match_type', 'unknown'),
                "score": result.get('score', 0),
                "files": [],
                "code_snippets": []
            }

            # Add file info
            for f in result.get('files', [])[:5]:  # Top 5 files
                enriched['files'].append({
                    "path": f.get('file_path', ''),
                    "type": f.get('change_type', ''),
                    "language": f.get('language', ''),
                    "lines": f"+{f.get('lines_added', 0)} -{f.get('lines_removed', 0)}"
                })

            # Add code snippet if available
            if result.get('snippet'):
                enriched['code_snippets'].append(result['snippet'])
            elif result.get('matching_functions'):
                # Add matching function signatures
                for func in result['matching_functions'][:3]:
                    enriched['code_snippets'].append(
                        f"{func['name']} (lines {func['start_line']}-{func['end_line']})"
                    )

            enriched_results.append(enriched)

        return {
            "query": search_result['query'],
            "search_type": search_result['search_type'],
            "count": search_result['count'],
            "repo_filter": repo_filter,
            "results": enriched_results
        }

    def extract_repo_filter_from_query(self, query: str) -> Tuple[str, Optional[str]]:
        """
        Extract repo filter from natural language query

        Args:
            query: User query like "show me code in sdc repos"

        Returns:
            (cleaned_query, repo_filter)
        """
        query_lower = query.lower()

        # Patterns for repo filtering
        patterns = [
            ("in repos with", "in the name"),
            ("in repo", ""),
            ("repos named", ""),
            ("in projects with", "in the name"),
            ("from repos", ""),
            ("repositories with", "in the name"),
        ]

        for pattern, suffix in patterns:
            if pattern in query_lower:
                # Extract repo name
                parts = query_lower.split(pattern)
                if len(parts) > 1:
                    after_pattern = parts[1].strip()
                    if suffix and suffix in after_pattern:
                        after_pattern = after_pattern.split(suffix)[0].strip()

                    # Get first word as repo filter
                    repo_filter = after_pattern.split()[0].strip('"\'')

                    # Clean query
                    cleaned = parts[0].strip()
                    return (cleaned, repo_filter)

        return (query, None)


def smart_search(query: str, limit: int = 20) -> Dict:
    """
    Smart search with automatic repo filtering and query parsing

    This is the recommended entry point for chat/AI usage

    Args:
        query: Natural language query
        limit: Max results

    Returns:
        Search results with context
    """
    searcher = UnifiedSearch()

    # Extract repo filter from query if present
    cleaned_query, repo_filter = searcher.extract_repo_filter_from_query(query)

    # Perform search
    return searcher.search_with_context(
        query=cleaned_query,
        repo_filter=repo_filter,
        limit=limit
    )


# Convenience functions for common search patterns

def search_my_code(query: str, limit: int = 20) -> List[Dict]:
    """Search user's code (all active repos)"""
    result = smart_search(query, limit)
    return result['results']


def search_in_repo(query: str, repo_name: str, limit: int = 20) -> List[Dict]:
    """Search within specific repo"""
    searcher = UnifiedSearch()
    result = searcher.search_with_context(query, repo_filter=repo_name, limit=limit)
    return result['results']


def search_by_language(query: str, language: str, limit: int = 20) -> List[Dict]:
    """Search code in specific language"""
    searcher = UnifiedSearch()
    result = searcher.search_with_context(query, language=language, limit=limit)
    return result['results']


def get_search_summary(search_result: Dict) -> str:
    """
    Generate human-readable summary of search results

    Args:
        search_result: Result from search_with_context()

    Returns:
        Formatted summary string
    """
    lines = []

    lines.append(f"Search: '{search_result['query']}'")
    lines.append(f"Type: {search_result['search_type']}")

    if search_result.get('repo_filter'):
        lines.append(f"Repo filter: {search_result['repo_filter']}")

    lines.append(f"Found: {search_result['count']} results")
    lines.append("")

    for i, result in enumerate(search_result['results'][:5], 1):
        lines.append(f"{i}. [{result['commit_hash']}] {result['message']}")
        lines.append(f"   Repo: {result['repo']}, Date: {result['date']}")
        lines.append(f"   Match: {result['match_type']} (score: {result['score']:.2f})")

        if result['files']:
            lines.append(f"   Files: {', '.join([f['path'] for f in result['files'][:3]])}")

        if result['code_snippets']:
            lines.append(f"   Code: {result['code_snippets'][0][:100]}...")

        lines.append("")

    if search_result['count'] > 5:
        lines.append(f"... and {search_result['count'] - 5} more results")

    return "\n".join(lines)
