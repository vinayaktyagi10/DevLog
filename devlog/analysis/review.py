"""
Review Pipeline - Orchestrate full code review with web research
"""
import json
from typing import Dict, List, Optional
from datetime import datetime
import sqlite3
from devlog.paths import DB_PATH
from devlog.core.embeddings import semantic_search
from devlog.analysis.analyzer import CodeAnalyzer
from devlog.search.web_search import WebSearcher
from devlog.search.scraper import WebScraper
from devlog.search.content_extractor import ContentExtractor
from devlog.analysis.compare import ComparisonEngine


class ReviewPipeline:
    """Full code review pipeline: analyze + research + compare"""

    def __init__(self):
        self.analyzer = CodeAnalyzer()
        self.searcher = WebSearcher()
        self.scraper = WebScraper()
        self.extractor = ContentExtractor()
        self.comparer = ComparisonEngine()

    def review_topic(
        self,
        topic: str,
        language: Optional[str] = None,
        num_commits: int = 5,
        deep_analysis: bool = False
    ) -> Dict:
        """
        Full code review pipeline

        Args:
            topic: Topic to review (e.g., "authentication", "database queries")
            language: Filter by programming language
            num_commits: Number of commits to analyze
            deep_analysis: Use deep analysis instead of quick

        Returns:
            Complete review with recommendations
        """
        print(f"🔍 Starting review for '{topic}'...")

        review = {
            'topic': topic,
            'language': language,
            'started_at': datetime.now().isoformat(),
            'steps': []
        }

        # Step 1: Find relevant commits
        print(f"   Finding your {topic}-related code...")
        commits = self._find_relevant_commits(topic, num_commits)

        if not commits:
            return {
                'error': f"No commits found related to '{topic}'",
                'suggestion': "Try a different topic or check your tracked repositories"
            }

        review['commits_found'] = len(commits)
        review['commit_hashes'] = [c['short_hash'] for c in commits]
        review['steps'].append(f"Found {len(commits)} relevant commits")

        # Step 2: Analyze your code
        print(f"   Analyzing your implementation...")
        analysis_type = 'deep' if deep_analysis else 'quick'
        your_analysis = self._analyze_commits(commits, analysis_type)
        review['your_analysis'] = your_analysis
        review['steps'].append(f"Analyzed {len(commits)} commits")

        # Extract code from commits for comparison
        your_code = self._extract_commit_code(commits)
        review['your_code_summary'] = {
            'total_lines': sum(len(code.split('\n')) for code in your_code),
            'files_analyzed': len(your_code)
        }

        # Step 3: Search web for best practices
        print(f"   Searching web for best practices...")
        search_results = self.searcher.search_topic(topic, language, num_results=10)
        review['web_search_results'] = len(search_results)
        review['steps'].append(f"Found {len(search_results)} web sources")

        if not search_results:
            review['steps'].append("Warning: No web results found")

        # Step 4: Scrape top sources
        print(f"   Scraping top sources...")
        top_urls = [r['url'] for r in search_results[:5]]  # Top 5
        scraped_content = self.scraper.scrape_multiple(top_urls)
        review['scraped_sources'] = len(scraped_content)
        review['steps'].append(f"Scraped {len(scraped_content)} sources")

        # Step 5: Extract best practices and examples
        print(f"   Extracting best practices...")
        web_practices = []
        web_examples = []

        for content in scraped_content:
            practices = self.extractor.extract_best_practices(content)
            web_practices.extend(practices)

            examples = self.extractor.extract_code_examples(content)
            web_examples.extend(examples)

        review['web_practices_found'] = len(web_practices)
        review['web_examples_found'] = len(web_examples)
        review['steps'].append(f"Extracted {len(web_practices)} practices, {len(web_examples)} examples")

        # Step 6: Compare your code with industry standards
        print(f"   Comparing with industry standards...")
        comparison = self.comparer.compare_implementations(
            your_code=' '.join(your_code),
            your_analysis=your_analysis,
            web_examples=web_examples,
            web_practices=web_practices,
            topic=topic
        )
        review['comparison'] = comparison
        review['steps'].append("Comparison complete")

        # Step 7: Store review
        review['completed_at'] = datetime.now().isoformat()
        review_id = self._store_review(review)
        review['id'] = review_id

        print(f"   ✓ Review complete (ID: {review_id})")

        return review

    def _find_relevant_commits(self, topic: str, limit: int) -> List[Dict]:
        """Find commits related to topic using semantic search"""
        # Use semantic search to find relevant commits
        results = semantic_search(topic, limit=limit)

        if not results:
            # Fallback: try keyword search
            from devlog.core.search import search_commits
            results = search_commits(topic, limit=limit)

        # Get full details for each commit
        commits = []
        for result in results:
            from devlog.core.search import get_commit_details
            details = get_commit_details(result['short_hash'])
            if details:
                commits.append(details)

        return commits

    def _analyze_commits(self, commits: List[Dict], analysis_type: str) -> Dict:
        """Analyze multiple commits and aggregate results"""
        all_issues = []
        all_suggestions = []
        all_patterns = []

        for commit in commits:
            analysis = self.analyzer.analyze_commit(commit['short_hash'], analysis_type)
            if analysis:
                all_issues.extend(analysis.get('issues', []))
                all_suggestions.extend(analysis.get('suggestions', []))

                patterns = analysis.get('patterns', [])
                if isinstance(patterns, dict):
                    all_patterns.extend(patterns.get('design_patterns', []))
                elif isinstance(patterns, list):
                    all_patterns.extend(patterns)

        # Deduplicate
        unique_issues = list(set(all_issues))
        unique_suggestions = list(set(all_suggestions))
        unique_patterns = list(set(all_patterns))

        return {
            'issues': unique_issues[:10],  # Top 10
            'suggestions': unique_suggestions[:10],
            'patterns': unique_patterns[:5],
            'total_commits_analyzed': len(commits)
        }

    def _extract_commit_code(self, commits: List[Dict]) -> List[str]:
        """Extract code from commits for comparison"""
        code_blocks = []

        for commit in commits:
            for change in commit.get('changes', []):
                if change.get('code_after'):
                    code_blocks.append(change['code_after'])

        return code_blocks

    def _store_review(self, review: Dict) -> int:
        """Store review in database"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Prepare data
        commit_ids = json.dumps(review.get('commit_hashes', []))
        your_analysis = json.dumps(review.get('your_analysis', {}))
        web_sources = json.dumps([{
            'title': 'Web sources',
            'count': review.get('scraped_sources', 0)
        }])
        comparison = json.dumps(review.get('comparison', {}))

        # Extract recommendations from comparison
        recommendations = review.get('comparison', {}).get('recommendations', [])
        recommendations_json = json.dumps(recommendations)

        c.execute("""
            INSERT INTO reviews (
                topic, commits_analyzed, your_code, your_analysis,
                web_sources, web_best_practices, comparison,
                recommendations, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            review['topic'],
            commit_ids,
            json.dumps(review.get('your_code_summary', {})),
            your_analysis,
            web_sources,
            json.dumps(review.get('web_practices_found', 0)),
            comparison,
            recommendations_json,
            review['completed_at']
        ))

        review_id = c.lastrowid
        conn.commit()
        conn.close()

        return review_id

    def get_review(self, review_id: int) -> Optional[Dict]:
        """Retrieve a stored review"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return None

        return dict(row)

    def list_reviews(self, limit: int = 20) -> List[Dict]:
        """List recent reviews"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT id, topic, created_at, commits_analyzed
            FROM reviews
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))

        reviews = [dict(row) for row in c.fetchall()]
        conn.close()

        return reviews

    def generate_report(self, review: Dict, format: str = 'text') -> str:
        """
        Generate human-readable review report

        Args:
            review: Review dictionary
            format: 'text' or 'markdown'

        Returns:
            Formatted report string
        """
        if format == 'markdown':
            return self._generate_markdown_report(review)
        else:
            return self._generate_text_report(review)

    def _generate_text_report(self, review: Dict) -> str:
        """Generate plain text report"""
        comparison = review.get('comparison', {})
        return self.comparer.generate_comparison_report(comparison)

    def _generate_markdown_report(self, review: Dict) -> str:
        """Generate markdown report"""
        lines = []

        lines.append(f"# Code Review: {review['topic']}\n")
        lines.append(f"**Date**: {review.get('completed_at', '')[:10]}\n")

        # Summary
        lines.append("## Summary\n")
        lines.append(f"- **Commits analyzed**: {review.get('commits_found', 0)}")
        lines.append(f"- **Web sources**: {review.get('scraped_sources', 0)}")
        lines.append(f"- **Best practices found**: {review.get('web_practices_found', 0)}")
        lines.append(f"- **Code examples**: {review.get('web_examples_found', 0)}\n")

        # Your implementation
        lines.append("## Your Implementation\n")
        your_analysis = review.get('your_analysis', {})
        if your_analysis.get('issues'):
            lines.append("### Issues Found\n")
            for issue in your_analysis['issues'][:5]:
                lines.append(f"- {issue}")
            lines.append("")

        # Comparison
        comparison = review.get('comparison', {})
        if comparison.get('matches'):
            lines.append("## ✓ Good Practices Already Following\n")
            for match in comparison['matches']:
                lines.append(f"- {match}")
            lines.append("")

        if comparison.get('gaps'):
            lines.append("## ⚠️ Gaps to Address\n")
            for gap in comparison['gaps'][:5]:
                lines.append(f"- **[{gap['severity'].upper()}]** {gap['practice']}")
            lines.append("")

        # Recommendations
        if comparison.get('recommendations'):
            lines.append("## Recommendations\n")
            for i, rec in enumerate(comparison['recommendations'][:5], 1):
                lines.append(f"### {i}. {rec['title']}\n")
                lines.append(f"{rec['description']}\n")
                if rec.get('code_example'):
                    lines.append("```")
                    lines.append(rec['code_example'][:300])
                    lines.append("```\n")
                if rec.get('source_url'):
                    lines.append(f"[Source]({rec['source_url']})\n")

        return '\n'.join(lines)


if __name__ == "__main__":
    print("Review Pipeline loaded successfully")
