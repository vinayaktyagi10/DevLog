"""
Tool Router - Intelligent tool selection with multi-stage reasoning

Replaces the weak single-LLM-call tool selection with a rule-based + LLM hybrid
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import re


class ToolType(Enum):
    """Available tools"""
    SEARCH_COMMITS = "search_commits"
    WEB_SEARCH = "web_search"
    NONE = "none"


class Intent(Enum):
    """User intent categories"""
    FACTUAL_LOCAL = "factual_local"
    FACTUAL_EXTERNAL = "factual_external"
    EVALUATIVE = "evaluative"
    HYPOTHETICAL = "hypothetical"
    CHAT = "chat"
    INVALID = "invalid"


@dataclass
class ToolDecision:
    """Tool selection decision"""
    tool: ToolType
    query: str
    confidence: float
    reasoning: str
    repo_filter: Optional[str] = None
    language_filter: Optional[str] = None


class ToolRouter:
    """
    Intelligent tool routing using rule-based heuristics + LLM fallback

    Much more reliable than pure LLM-based tool selection
    """

    def __init__(self):
        # Patterns for commit search
        self.commit_search_patterns = [
            r'\b(my|our|the)\s+(commits?|changes?|code|work)\b',
            r'\b(what|show|find|search)\s+.*\b(did|worked|changed|committed)\b',
            r'\b(yesterday|today|last\s+\w+|recent)\b',
            r'\brepo(sitory)?\s+\w+\b',
            r'\bcommits?\s+(in|from|about|with)\b',
            r'\bfile\s+\w+\b',
            r'\bfunction\s+\w+\b',
            r'\bclass\s+\w+\b',
        ]

        # Patterns for web search
        self.web_search_patterns = [
            r'\b(how\s+to|best\s+practice|tutorial|guide|documentation)\b',
            r'\b(what\s+is|explain|define)\b',
            r'\b(latest|new|current)\s+(version|release)\b',
            r'\b(library|framework|tool|package)\s+\w+\b',
            r'\b(error|exception|bug)\s+.*\b(fix|solve|resolve)\b',
        ]

        # Repo name extraction patterns
        self.repo_patterns = [
            r'repo(?:sitory)?\s+(?:named|called)?\s*["\']?(\w+)["\']?',
            r'in\s+(?:the\s+)?["\']?(\w+)["\']?\s+repo',
            r'repos?\s+with\s+["\']?(\w+)["\']?',
            r'["\'](\w+)["\']?\s+project',
        ]

        # Language extraction patterns
        self.language_patterns = [
            r'\b(python|javascript|typescript|java|go|rust|c\+\+|ruby|php)\b',
            r'\.py\b',
            r'\.js\b',
            r'\.ts\b',
            r'\.java\b',
            r'\.go\b',
        ]

    def route(self, query: str, intent: Intent) -> ToolDecision:
        """
        Route query to appropriate tool

        Args:
            query: User query
            intent: Classified intent

        Returns:
            ToolDecision with tool, query, confidence, and filters
        """
        query_lower = query.lower()

        # Rule 1: Non-factual intents don't need tools
        if intent not in [Intent.FACTUAL_LOCAL, Intent.FACTUAL_EXTERNAL]:
            return ToolDecision(
                tool=ToolType.NONE,
                query="",
                confidence=1.0,
                reasoning=f"Intent {intent.value} doesn't require tools"
            )

        # Rule 2: Extract filters from query
        repo_filter = self._extract_repo_filter(query_lower)
        language_filter = self._extract_language(query_lower)

        # Rule 3: Pattern-based tool selection
        commit_score = self._score_patterns(query_lower, self.commit_search_patterns)
        web_score = self._score_patterns(query_lower, self.web_search_patterns)

        # Rule 4: Intent-based boosting
        if intent == Intent.FACTUAL_LOCAL:
            commit_score += 0.3
        elif intent == Intent.FACTUAL_EXTERNAL:
            web_score += 0.3

        # Rule 5: Make decision
        if commit_score > web_score and commit_score > 0.3:
            # Use commit search
            search_query = self._clean_query_for_search(query)
            return ToolDecision(
                tool=ToolType.SEARCH_COMMITS,
                query=search_query,
                confidence=min(commit_score, 1.0),
                reasoning=f"Matched commit search patterns (score: {commit_score:.2f})",
                repo_filter=repo_filter,
                language_filter=language_filter
            )

        elif web_score > 0.3:
            # Use web search
            return ToolDecision(
                tool=ToolType.WEB_SEARCH,
                query=query,
                confidence=min(web_score, 1.0),
                reasoning=f"Matched web search patterns (score: {web_score:.2f})"
            )

        else:
            # Low confidence - no tool
            return ToolDecision(
                tool=ToolType.NONE,
                query="",
                confidence=0.5,
                reasoning="No strong pattern match, will answer directly"
            )

    def _score_patterns(self, query: str, patterns: list) -> float:
        """Score query against list of regex patterns"""
        matches = 0
        for pattern in patterns:
            if re.search(pattern, query, re.IGNORECASE):
                matches += 1

        # Normalize score between 0 and 1
        if not patterns:
            return 0.0

        return min(matches / len(patterns) * 2, 1.0)

    def _extract_repo_filter(self, query: str) -> Optional[str]:
        """Extract repository name from query"""
        for pattern in self.repo_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _extract_language(self, query: str) -> Optional[str]:
        """Extract programming language from query"""
        for pattern in self.language_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                lang = match.group(0).lower()
                # Normalize language names
                lang_map = {
                    'c++': 'cpp',
                    '.py': 'python',
                    '.js': 'javascript',
                    '.ts': 'typescript',
                    '.java': 'java',
                    '.go': 'go',
                }
                return lang_map.get(lang, lang)

        return None

    def _clean_query_for_search(self, query: str) -> str:
        """
        Clean query for search by removing noise words
        """
        # Remove common phrases that don't help search
        noise_patterns = [
            r'\b(show|find|search|get|give|tell)\s+me\b',
            r'\b(i|my|our|the)\b',
            r'\b(what|where|when|how)\b',
            r'\b(did|do|does|done)\b',
            r'\brepo(?:sitory)?\s+(?:named|called)?\s+',
            r'\bcommits?\s+(in|from|about|with)\b',
        ]

        cleaned = query.lower()
        for pattern in noise_patterns:
            cleaned = re.sub(pattern, ' ', cleaned, flags=re.IGNORECASE)

        # Remove extra whitespace
        cleaned = ' '.join(cleaned.split())

        return cleaned.strip() or query


# ==================== CONVENIENCE FUNCTION ====================

def route_tool(query: str, intent: Intent) -> ToolDecision:
    """
    Convenience function for tool routing
    """
    router = ToolRouter()
    return router.route(query, intent)
