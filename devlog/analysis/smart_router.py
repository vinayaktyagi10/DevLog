"""
Smart Tool Router - LLM-assisted tool selection with entity extraction
"""

import re
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum

from devlog.analysis.llm import analyze_code


class Intent(Enum):
    """User intent categories"""
    SEARCH_CODE = "search_code"
    ANALYZE_CODE = "analyze_code"
    REVIEW_CODE = "review_code"
    SHOW_INFO = "show_info"
    COMPARE = "compare"
    WEB_RESEARCH = "web_research"
    UTILITY = "utility"
    CHAT = "chat"


@dataclass
class EntityExtraction:
    """Extracted entities from query"""
    commit_hashes: List[str]
    repo_names: List[str]
    file_paths: List[str]
    languages: List[str]
    topics: List[str]
    time_references: List[str]
    numbers: List[int]


@dataclass
class RoutingDecision:
    """Tool routing decision"""
    tool_name: str
    parameters: Dict[str, Any]
    confidence: float
    reasoning: str
    entities: EntityExtraction
    fallback_tools: List[str]


class SmartToolRouter:
    """
    Intelligent tool routing using:
    1. Rule-based pattern matching (fast)
    2. Entity extraction (regex + heuristics)
    3. LLM-assisted routing (when uncertain)
    """

    def __init__(self):
        # Commit hash patterns
        self.commit_pattern = re.compile(r'\b[0-9a-f]{7,40}\b', re.I)

        # Language patterns
        self.language_keywords = {
            'python': ['python', 'py', '.py'],
            'javascript': ['javascript', 'js', '.js', 'node'],
            'typescript': ['typescript', 'ts', '.ts'],
            'java': ['java', '.java'],
            'go': ['golang', 'go', '.go'],
            'rust': ['rust', 'rs', '.rs'],
            'cpp': ['c++', 'cpp', '.cpp', '.h'],
        }

        # Tool selection patterns
        self.tool_patterns = {
            'search_commits': [
                r'\b(find|search|show|get|list)\b.*\b(commit|change|work|code)\b',
                r'\bwhat (did|have) i\b',
                r'\b(recent|last|yesterday|today)\b.*\b(commit|work)\b',
            ],
            'analyze_commit': [
                r'\b(analyze|review|check|examine|look at)\b.*\b(commit|this|that)\b',
                r'\banalyze\b.*\b[0-9a-f]{7}\b',
                r'\b(issues|problems|bugs) in\b.*\bcommit\b',
            ],
            'show_commit': [
                r'\b(show|display|view)\b.*\b(commit|details|info)\b.*\b[0-9a-f]{7}\b',
                r'\b[0-9a-f]{7}\b.*\b(details|info|what|show)\b',
            ],
            'start_review': [
                r'\b(review|audit)\b.*\b(code|implementation)\b',
                r'\breview\b.*\b(auth|login|api|database)\b',
                r'\b(how|what).*(auth|security|performance)\b.*\b(implementation|approach)\b',
            ],
            'compare_commits': [
                r'\bcompare\b.*\bcommits?\b',
                r'\b(difference|diff) between\b.*\b[0-9a-f]{7}\b',
            ],
            'web_search': [
                r'\b(search|find|look up|research)\b.*\b(web|online|google)\b',
                r'\b(best practice|how to|tutorial|guide)\b',
                r'\b(what is|explain|define)\b.*(?!commit)',
            ],
            'show_stats': [
                r'\b(stats|statistics|summary|overview|activity)\b',
                r'\bhow (many|much)\b.*\b(commit|work|code)\b',
            ],
            'list_repos': [
                r'\b(list|show|what)\b.*\b(repos?|repositories)\b',
            ],
        }

        # Time reference patterns
        self.time_patterns = {
            'today': r'\btoday\b',
            'yesterday': r'\byesterday\b',
            'this week': r'\bthis week\b',
            'last week': r'\blast week\b',
            'this month': r'\bthis month\b',
        }

    async def route(self, query: str, context: Optional[Dict] = None) -> RoutingDecision:
        """
        Route query to appropriate tool

        Args:
            query: User query
            context: Optional context (recent commits, current repo, etc.)

        Returns:
            RoutingDecision with tool, parameters, confidence
        """
        query_lower = query.lower()

        # Step 1: Extract entities
        entities = self._extract_entities(query, context)

        # Step 2: Pattern-based routing (fast path)
        pattern_result = self._route_by_patterns(query_lower, entities)

        if pattern_result and pattern_result.confidence > 0.7:
            return pattern_result

        # Step 3: LLM-assisted routing (uncertain cases)
        llm_result = await self._route_by_llm(query, entities, pattern_result)

        return llm_result or pattern_result or self._default_routing(query, entities)

    def _extract_entities(self, query: str, context: Optional[Dict] = None) -> EntityExtraction:
        """Extract entities from query"""

        # Commit hashes
        commit_hashes = self.commit_pattern.findall(query)

        # Languages
        languages = []
        query_lower = query.lower()
        for lang, keywords in self.language_keywords.items():
            if any(kw in query_lower for kw in keywords):
                languages.append(lang)

        # Repo names (simple heuristic: capitalized words after "in" or "repo")
        repo_pattern = r'(?:in|repo(?:sitory)?)\s+([A-Z][a-zA-Z0-9_-]+)'
        repo_names = re.findall(repo_pattern, query)

        # Also check for lowercase after explicit markers
        repo_pattern2 = r'(?:repo|repository|project)\s+["\']?([a-z][a-z0-9_-]+)["\']?'
        repo_names.extend(re.findall(repo_pattern2, query_lower))

        # File paths
        file_pattern = r'(?:file|path)?\s*([a-zA-Z0-9_/-]+\.[a-z]{2,5})'
        file_paths = re.findall(file_pattern, query)

        # Topics (nouns that might be review topics)
        topic_pattern = r'\b(auth(?:entication)?|login|api|database|security|error|logging|testing|deployment)\b'
        topics = list(set(re.findall(topic_pattern, query_lower)))

        # Time references
        time_refs = []
        for time_name, pattern in self.time_patterns.items():
            if re.search(pattern, query_lower):
                time_refs.append(time_name)

        # Numbers
        numbers = [int(n) for n in re.findall(r'\b(\d+)\b', query)]

        return EntityExtraction(
            commit_hashes=commit_hashes,
            repo_names=list(set(repo_names)),
            file_paths=file_paths,
            languages=languages,
            topics=topics,
            time_references=time_refs,
            numbers=numbers
        )

    def _route_by_patterns(self, query: str, entities: EntityExtraction) -> Optional[RoutingDecision]:
        """Route using pattern matching"""

        # Score each tool
        scores = {}

        for tool_name, patterns in self.tool_patterns.items():
            score = 0.0
            for pattern in patterns:
                if re.search(pattern, query, re.I):
                    score += 0.4

            # Bonus for relevant entities
            if tool_name == 'analyze_commit' and entities.commit_hashes:
                score += 0.3
            if tool_name == 'start_review' and entities.topics:
                score += 0.2
            if tool_name in ['search_commits', 'show_commit'] and entities.commit_hashes:
                score += 0.2
            if entities.repo_names:
                score += 0.1

            if score > 0:
                scores[tool_name] = min(score, 1.0)

        if not scores:
            return None

        # Best tool
        best_tool = max(scores.items(), key=lambda x: x[1])
        tool_name, confidence = best_tool

        # Build parameters
        params = self._build_parameters(tool_name, query, entities)

        return RoutingDecision(
            tool_name=tool_name,
            parameters=params,
            confidence=confidence,
            reasoning=f"Pattern match: {confidence:.2f} confidence",
            entities=entities,
            fallback_tools=self._get_fallback_tools(tool_name, scores)
        )

    async def _route_by_llm(
        self,
        query: str,
        entities: EntityExtraction,
        pattern_result: Optional[RoutingDecision]
    ) -> Optional[RoutingDecision]:
        """Use LLM for uncertain routing decisions"""

        # Build context
        context_parts = [
            f"Query: {query}",
            f"Extracted entities:",
            f"  Commits: {', '.join(entities.commit_hashes) or 'none'}",
            f"  Repos: {', '.join(entities.repo_names) or 'none'}",
            f"  Languages: {', '.join(entities.languages) or 'none'}",
            f"  Topics: {', '.join(entities.topics) or 'none'}",
        ]

        if pattern_result:
            context_parts.append(f"Pattern suggests: {pattern_result.tool_name} ({pattern_result.confidence:.2f})")

        # Get dynamic tool list
        from devlog.analysis.tool_registry import get_tool_registry
        registry = get_tool_registry()

        context_parts.append("\nAvailable tools:")
        for tool in registry.list_tools():
            context_parts.append(f"- {tool.name}: {tool.description}")
        context_parts.append("- none: No tool needed (chat response)")

        context_parts.append("\nOutput ONLY the tool name (or 'none'):")

        prompt = "\n".join(context_parts)

        try:
            # Quick LLM call for tool selection
            response = await analyze_code(
                prompt=prompt,
                code="",
                language="text",
                stream=False,
                temperature=0.0,
                stop=["\n"]
            )

            tool_name = response.strip().lower()

            # Validate tool name
            valid_tools = list(self.tool_patterns.keys()) + ['none']
            if tool_name not in valid_tools:
                return None

            if tool_name == 'none':
                return RoutingDecision(
                    tool_name='none',
                    parameters={},
                    confidence=0.8,
                    reasoning="LLM determined no tool needed",
                    entities=entities,
                    fallback_tools=[]
                )

            params = self._build_parameters(tool_name, query, entities)

            return RoutingDecision(
                tool_name=tool_name,
                parameters=params,
                confidence=0.85,
                reasoning=f"LLM routing to {tool_name}",
                entities=entities,
                fallback_tools=[]
            )

        except Exception as e:
            print(f"LLM routing failed: {e}")
            return None

    def _build_parameters(self, tool_name: str, query: str, entities: EntityExtraction) -> Dict[str, Any]:
        """Build parameters for a tool based on entities"""

        params = {}

        if tool_name in ['search_commits', 'semantic_search']:
            # Use original query, but clean it
            params['query'] = self._clean_search_query(query)

            if entities.repo_names:
                params['repo'] = entities.repo_names[0]
            if entities.languages:
                params['language'] = entities.languages[0]
            if entities.numbers:
                params['limit'] = min(entities.numbers[0], 30)

        elif tool_name == 'analyze_commit':
            if entities.commit_hashes:
                params['commit_hash'] = entities.commit_hashes[0]
            else:
                # No explicit hash - might need to search first
                params['commit_hash'] = 'NEEDS_SEARCH'

            params['analysis_type'] = 'quick'

            # Check for deep analysis keywords
            if any(kw in query.lower() for kw in ['deep', 'thorough', 'detailed', 'comprehensive']):
                params['analysis_type'] = 'deep'

        elif tool_name == 'show_commit':
            if entities.commit_hashes:
                params['commit_hash'] = entities.commit_hashes[0]
            else:
                params['commit_hash'] = 'NEEDS_SEARCH'

        elif tool_name == 'start_review':
            if entities.topics:
                params['topic'] = entities.topics[0]
            else:
                # Extract from query
                params['topic'] = self._extract_review_topic(query)

            if entities.languages:
                params['language'] = entities.languages[0]
            if entities.numbers:
                params['num_commits'] = min(entities.numbers[0], 10)

        elif tool_name == 'compare_commits':
            if len(entities.commit_hashes) >= 2:
                params['commit_hashes'] = ','.join(entities.commit_hashes)
            else:
                params['commit_hashes'] = 'NEEDS_MORE_HASHES'

        elif tool_name == 'web_search':
            params['query'] = query
            if entities.numbers:
                params['limit'] = min(entities.numbers[0], 20)

        return params

    def _clean_search_query(self, query: str) -> str:
        """Clean up search query by removing noise words"""
        noise_words = [
            'show', 'find', 'search', 'get', 'list', 'me', 'my', 'i',
            'want', 'need', 'please', 'can', 'you', 'the', 'all'
        ]

        words = query.lower().split()
        cleaned = [w for w in words if w not in noise_words]

        return ' '.join(cleaned) if cleaned else query

    def _extract_review_topic(self, query: str) -> str:
        """Extract review topic from query"""
        # Remove common prefixes
        query_lower = query.lower()

        patterns = [
            r'review\s+(?:my\s+)?(.+?)(?:\s+code|\s+implementation|$)',
            r'(?:how|what).+?(?:about|with)\s+(.+?)(?:\s+code|\s+implementation|$)',
        ]

        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                return match.group(1).strip()

        # Fallback: use first topic or entire query
        return query[:50]

    def _get_fallback_tools(self, primary: str, scores: Dict[str, float]) -> List[str]:
        """Get fallback tools if primary fails"""
        sorted_tools = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [name for name, score in sorted_tools[1:3] if score > 0.3]

    def _default_routing(self, query: str, entities: EntityExtraction) -> RoutingDecision:
        """Default routing when nothing else matches"""

        # If commit hash present, probably want to see it
        if entities.commit_hashes:
            return RoutingDecision(
                tool_name='show_commit',
                parameters={'commit_hash': entities.commit_hashes[0]},
                confidence=0.5,
                reasoning="Default: commit hash detected",
                entities=entities,
                fallback_tools=['search_commits']
            )

        # Otherwise, probably a search
        return RoutingDecision(
            tool_name='search_commits',
            parameters={'query': query, 'limit': 15},
            confidence=0.4,
            reasoning="Default: search commits",
            entities=entities,
            fallback_tools=['semantic_search']
        )
