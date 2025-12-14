"""
Web Search Module - Search for best practices and documentation - FIXED
"""
import os
from typing import List, Dict, Optional
import time


class WebSearcher:
    """Search the web for technical content and best practices"""

    def __init__(self):
        self.brave_api_key = os.getenv('BRAVE_API_KEY')
        self.use_brave = bool(self.brave_api_key)
        self.cache = {}  # Simple in-memory cache

    def search(self, query: str, num_results: int = 10) -> List[Dict]:
        """
        Search the web for a query

        Args:
            query: Search query
            num_results: Number of results to return

        Returns:
            List of search results with title, url, snippet, source
        """
        # Check cache first
        cache_key = f"{query}:{num_results}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Try Brave first, fallback to DuckDuckGo
        if self.use_brave:
            results = self._search_brave(query, num_results)
        else:
            results = self._search_duckduckgo(query, num_results)

        # Rank and filter results
        results = self._rank_results(results)

        # Cache results
        self.cache[cache_key] = results

        return results

    def _search_brave(self, query: str, num_results: int) -> List[Dict]:
        """Search using Brave Search API"""
        import httpx

        try:
            response = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": self.brave_api_key},
                params={"q": query, "count": num_results},
                timeout=10
            )

            if response.status_code != 200:
                print(f"Brave API error: {response.status_code}, falling back to DuckDuckGo")
                return self._search_duckduckgo(query, num_results)

            data = response.json()
            results = []

            for item in data.get('web', {}).get('results', []):
                results.append({
                    'title': item.get('title', ''),
                    'url': item.get('url', ''),
                    'snippet': item.get('description', ''),
                    'source': self._extract_domain(item.get('url', '')),
                    'engine': 'brave'
                })

            return results

        except Exception as e:
            print(f"Brave search failed: {e}, falling back to DuckDuckGo")
            return self._search_duckduckgo(query, num_results)

    def _search_duckduckgo(self, query: str, num_results: int) -> List[Dict]:
        """Search using DuckDuckGo (no API key needed) - FIXED"""
        try:
            # Try new package name first
            try:
                from ddgs import DDGS
            except ImportError:
                # Fallback to old package name
                from duckduckgo_search import DDGS

            ddgs = DDGS()

            # Use the correct method - text() returns an iterator
            raw_results = list(ddgs.text(query, max_results=num_results))

            if not raw_results:
                print(f"DuckDuckGo returned no results for: {query}")
                return []

            results = []
            for item in raw_results:
                results.append({
                    'title': item.get('title', ''),
                    'url': item.get('href', ''),
                    'snippet': item.get('body', ''),
                    'source': self._extract_domain(item.get('href', '')),
                    'engine': 'duckduckgo'
                })

            return results

        except Exception as e:
            print(f"DuckDuckGo search failed: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL for source attribution"""
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except:
            return 'unknown'

    def _rank_results(self, results: List[Dict]) -> List[Dict]:
        """
        Rank search results by relevance and authority

        Priority sources (higher score):
        1. Official documentation (python.org, nodejs.org, etc.)
        2. Stack Overflow
        3. GitHub
        4. Well-known tech blogs (dev.to, medium.com, etc.)
        """
        authority_scores = {
            'stackoverflow.com': 1.0,
            'github.com': 0.9,
            'python.org': 1.0,
            'nodejs.org': 1.0,
            'mozilla.org': 1.0,  # MDN
            'dev.to': 0.8,
            'medium.com': 0.7,
            'auth0.com': 0.9,
            'owasp.org': 1.0,
            'realpython.com': 0.9,
        }

        for result in results:
            source = result['source']

            # Base score from authority
            score = authority_scores.get(source, 0.5)

            # Boost for documentation keywords
            title_lower = result['title'].lower()
            if any(kw in title_lower for kw in ['documentation', 'official', 'guide']):
                score += 0.2

            # Boost for recent years
            if any(year in result['title'] for year in ['2024', '2023']):
                score += 0.1

            result['score'] = min(score, 1.0)

        # Sort by score (highest first)
        results.sort(key=lambda x: x['score'], reverse=True)

        return results

    def generate_query(self, topic: str, language: str = None) -> str:
        """
        Generate optimized search query with technical context

        Args:
            topic: Topic to search for (e.g., "authentication", "JWT", "chore")
            language: Programming language filter

        Returns:
            Optimized search query string
        """
        # Always enforce technical context
        technical_keywords = ["best practices", "programming", "software engineering"]
        
        # If topic is a common ambiguous term, add specific qualifiers
        ambiguous_terms = {
            'chore': 'git commit message',
            'feat': 'git commit message',
            'fix': 'git commit message',
            'refactor': 'code refactoring',
            'ci': 'continuous integration',
            'docs': 'documentation'
        }
        
        refined_topic = ambiguous_terms.get(topic.lower(), topic)
        
        query_parts = [refined_topic]
        
        if language:
            query_parts.append(language)
            
        # Add technical keywords to ensure we get dev-related results
        query_parts.extend(technical_keywords)

        return " ".join(query_parts)

    def search_topic(self, topic: str, language: str = None, num_results: int = 10) -> List[Dict]:
        """
        Search for best practices on a specific topic

        Args:
            topic: Topic (e.g., "JWT authentication", "password hashing")
            language: Programming language filter
            num_results: Number of results

        Returns:
            Ranked search results
        """
        query = self.generate_query(topic, language)
        return self.search(query, num_results)

    def search_code_examples(self, topic: str, language: str, num_results: int = 5) -> List[Dict]:
        """
        Search specifically for code examples

        Args:
            topic: What to search for
            language: Programming language
            num_results: Number of results

        Returns:
            Results filtered for code examples
        """
        query = f"{topic} {language} code example"
        results = self.search(query, num_results)

        # Prefer Stack Overflow and GitHub
        prioritized = []
        others = []

        for result in results:
            if result['source'] in ['stackoverflow.com', 'github.com']:
                prioritized.append(result)
            else:
                others.append(result)

        return prioritized + others

    def search_documentation(self, library: str, topic: str = None) -> List[Dict]:
        """
        Search for official documentation

        Args:
            library: Library/framework name (e.g., "Flask", "Express")
            topic: Specific topic within docs

        Returns:
            Documentation search results
        """
        query = f"{library} official documentation"
        if topic:
            query += f" {topic}"

        results = self.search(query, num_results=5)

        # Filter for official sources only
        official_domains = [
            'python.org', 'nodejs.org', 'flask.palletsprojects.com',
            'expressjs.com', 'reactjs.org', 'vuejs.org', 'angular.io',
            'djangoproject.com', 'rubyonrails.org'
        ]

        return [r for r in results if any(d in r['source'] for d in official_domains)]


def test_search():
    """Quick test function"""
    searcher = WebSearcher()

    print("Testing web search...")
    print(f"Using: {'Brave' if searcher.use_brave else 'DuckDuckGo'}")
    print()

    # Test basic search
    results = searcher.search_topic("JWT authentication", "Python", num_results=5)

    if not results:
        print("No results found. Trying simpler query...")
        results = searcher.search("JWT authentication", num_results=5)

    print(f"Found {len(results)} results:\n")

    for i, result in enumerate(results, 1):
        print(f"{i}. [{result['score']:.2f}] {result['title']}")
        print(f"   {result['source']}")
        print(f"   {result['url']}")
        print(f"   {result['snippet'][:100]}...")
        print()


if __name__ == "__main__":
    test_search()
