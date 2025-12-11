"""
Comparison Engine - Compare your code with industry best practices
"""
from typing import List, Dict
from devlog.analysis.llm import analyze_code


class ComparisonEngine:
    """Compare user's code with web-sourced best practices"""

    def __init__(self):
        pass

    def compare_implementations(
        self,
        your_code: str,
        your_analysis: Dict,
        web_examples: List[Dict],
        web_practices: List[str],
        topic: str
    ) -> Dict:
        """
        Compare your implementation with industry standards

        Args:
            your_code: Your source code
            your_analysis: AI analysis of your code
            web_examples: Code examples from web
            web_practices: Best practices from web
            topic: Topic being reviewed

        Returns:
            Comparison results with gaps and recommendations
        """
        comparison = {
            'topic': topic,
            'your_approach': self._summarize_your_approach(your_code, your_analysis),
            'industry_approach': self._summarize_industry_approach(web_examples, web_practices),
            'matches': [],
            'gaps': [],
            'different_approaches': [],
            'recommendations': []
        }

        # Identify what matches
        comparison['matches'] = self._find_matches(your_analysis, web_practices)

        # Identify gaps (what you're missing)
        comparison['gaps'] = self._find_gaps(your_analysis, web_practices, web_examples)

        # Identify different approaches
        comparison['different_approaches'] = self._find_differences(
            your_code, web_examples, topic
        )

        # Generate specific recommendations
        comparison['recommendations'] = self._generate_recommendations(
            comparison['gaps'],
            comparison['different_approaches'],
            web_examples
        )

        return comparison

    def _summarize_your_approach(self, code: str, analysis: Dict) -> Dict:
        """Summarize how the user implemented something"""
        summary = {
            'code_length': len(code.splitlines()),
            'patterns_used': [],
            'issues_found': analysis.get('issues', []),
            'positive_aspects': []
        }

        # Extract patterns from analysis
        if 'patterns' in analysis:
            patterns = analysis['patterns']
            if isinstance(patterns, dict):
                summary['patterns_used'] = patterns.get('design_patterns', [])
            elif isinstance(patterns, list):
                summary['patterns_used'] = patterns

        # Identify positive aspects (opposite of issues)
        if len(summary['issues_found']) < 3:
            summary['positive_aspects'].append("Few critical issues detected")

        return summary

    def _summarize_industry_approach(self, examples: List[Dict], practices: List[str]) -> Dict:
        """Summarize industry best practices"""
        return {
            'num_sources': len(examples),
            'key_practices': practices[:10],
            'common_patterns': self._identify_common_patterns(examples),
            'recommended_libraries': self._identify_libraries(examples)
        }

    def _find_matches(self, your_analysis: Dict, web_practices: List[str]) -> List[str]:
        """Find what you're already doing right"""
        matches = []

        # Check your code's positive aspects against best practices
        your_text = ' '.join([
            str(your_analysis.get('summary', '')),
            ' '.join(your_analysis.get('suggestions', []))
        ]).lower()

        for practice in web_practices:
            practice_keywords = practice.lower().split()

            # If practice mentions things you're already doing
            if any(keyword in your_text for keyword in practice_keywords[:3]):
                # But it's not flagged as an issue
                if not any(keyword in issue.lower() for issue in your_analysis.get('issues', []) for keyword in practice_keywords[:2]):
                    matches.append(practice)

        return matches[:5]  # Top 5 matches

    def _find_gaps(
        self,
        your_analysis: Dict,
        web_practices: List[str],
        web_examples: List[Dict]
    ) -> List[Dict]:
        """Find what you're missing compared to best practices"""
        gaps = []

        # Check issues against best practices
        your_issues = [issue.lower() for issue in your_analysis.get('issues', [])]

        for practice in web_practices:
            practice_lower = practice.lower()

            # Key phrases that indicate gaps
            gap_indicators = ['should', 'must', 'always', 'never', 'avoid', 'ensure']

            if any(indicator in practice_lower for indicator in gap_indicators):
                # Check if this addresses one of your issues
                is_relevant = any(
                    any(word in issue for word in practice_lower.split()[:5])
                    for issue in your_issues
                )

                if is_relevant or len(gaps) < 3:  # Take at least 3 gaps
                    gaps.append({
                        'practice': practice,
                        'severity': 'high' if any(word in practice_lower for word in ['must', 'never', 'security']) else 'medium',
                        'addressed_by_examples': self._find_relevant_examples(practice, web_examples)
                    })

        return gaps[:10]  # Top 10 gaps

    def _find_differences(self, your_code: str, web_examples: List[Dict], topic: str) -> List[Dict]:
        """Find where your approach differs from industry standard"""
        differences = []

        # Use LLM to compare approaches
        if web_examples:
            # Take best example (highest quality score)
            best_example = max(web_examples, key=lambda x: len(x.get('code', '')))

            if best_example.get('code'):
                prompt = f"""Compare these two implementations of {topic}:

YOUR CODE:
{your_code[:1000]}

INDUSTRY EXAMPLE:
{best_example['code'][:1000]}

Identify key differences in approach:
DIFFERENCES:
- [specific difference]: Your approach vs Standard approach"""

                comparison_text = analyze_code(prompt, your_code[:500], 'text')

                # Parse differences
                for line in comparison_text.split('\n'):
                    if line.strip().startswith('-'):
                        diff_text = line.strip()[1:].strip()
                        if len(diff_text) > 20:
                            differences.append({
                                'description': diff_text,
                                'example_source': best_example.get('source_url', '')
                            })

        return differences[:5]

    def _generate_recommendations(
        self,
        gaps: List[Dict],
        differences: List[Dict],
        examples: List[Dict]
    ) -> List[Dict]:
        """Generate actionable recommendations with code examples"""
        recommendations = []

        # Recommendations from gaps
        for gap in gaps[:5]:
            rec = {
                'title': self._extract_recommendation_title(gap['practice']),
                'description': gap['practice'],
                'priority': gap['severity'],
                'code_example': None,
                'source_url': None
            }

            # Find relevant code example
            relevant_examples = gap.get('addressed_by_examples', [])
            if relevant_examples:
                best_example = relevant_examples[0]
                rec['code_example'] = best_example.get('code', '')
                rec['source_url'] = best_example.get('source_url', '')

            recommendations.append(rec)

        # Recommendations from differences
        for diff in differences:
            rec = {
                'title': 'Consider alternative approach',
                'description': diff['description'],
                'priority': 'medium',
                'code_example': None,
                'source_url': diff.get('example_source')
            }
            recommendations.append(rec)

        return recommendations[:10]

    def _extract_recommendation_title(self, practice: str) -> str:
        """Extract a concise title from a best practice statement"""
        # Take first few words, up to 60 characters
        words = practice.split()
        title = ' '.join(words[:8])
        if len(title) > 60:
            title = title[:60] + '...'
        return title

    def _identify_common_patterns(self, examples: List[Dict]) -> List[str]:
        """Identify patterns commonly used in examples"""
        patterns = []

        for example in examples:
            code = example.get('code', '').lower()

            # Check for common patterns
            if 'class' in code and 'factory' in example.get('context', '').lower():
                patterns.append('Factory Pattern')
            if 'middleware' in code or 'decorator' in code:
                patterns.append('Middleware/Decorator Pattern')
            if 'try:' in code and 'except' in code:
                patterns.append('Error Handling')
            if 'import logging' in code or 'logger' in code:
                patterns.append('Logging')

        # Return unique patterns
        return list(set(patterns))

    def _identify_libraries(self, examples: List[Dict]) -> List[str]:
        """Identify commonly recommended libraries"""
        libraries = []

        for example in examples:
            code = example.get('code', '')

            # Extract import statements
            import_lines = [line for line in code.split('\n') if 'import' in line.lower()]

            for line in import_lines:
                # Simple extraction
                if 'from' in line.lower():
                    parts = line.split('from')[1].split('import')[0].strip()
                    library = parts.split('.')[0]
                    libraries.append(library)
                elif 'import' in line.lower():
                    library = line.split('import')[1].strip().split('.')[0].split()[0]
                    libraries.append(library)

        # Return unique, most common
        from collections import Counter
        common = Counter(libraries).most_common(5)
        return [lib for lib, count in common if count > 1]

    def _find_relevant_examples(self, practice: str, examples: List[Dict]) -> List[Dict]:
        """Find examples that demonstrate a specific practice"""
        relevant = []
        practice_lower = practice.lower()

        for example in examples:
            # Check if example context or code mentions the practice
            context = example.get('context', '').lower()
            code = example.get('code', '').lower()

            # Extract keywords from practice
            keywords = [word for word in practice_lower.split() if len(word) > 4][:3]

            if any(keyword in context or keyword in code for keyword in keywords):
                relevant.append(example)

        return relevant[:3]  # Top 3 relevant examples

    def generate_comparison_report(self, comparison: Dict) -> str:
        """Generate human-readable comparison report"""
        lines = []

        lines.append(f"=== Code Review: {comparison['topic']} ===\n")

        # Your approach
        lines.append("YOUR IMPLEMENTATION:")
        your_approach = comparison['your_approach']
        lines.append(f"  Code size: {your_approach['code_length']} lines")
        if your_approach['patterns_used']:
            lines.append(f"  Patterns used: {', '.join(your_approach['patterns_used'][:3])}")
        lines.append(f"  Issues found: {len(your_approach['issues_found'])}")
        lines.append("")

        # Matches (what you're doing right)
        if comparison['matches']:
            lines.append("✓ GOOD PRACTICES ALREADY FOLLOWING:")
            for match in comparison['matches']:
                lines.append(f"  • {match}")
            lines.append("")

        # Gaps (what you're missing)
        if comparison['gaps']:
            lines.append("⚠ GAPS TO ADDRESS:")
            for gap in comparison['gaps']:
                priority_mark = "🔴" if gap['severity'] == 'high' else "🟡"
                lines.append(f"  {priority_mark} {gap['practice']}")
            lines.append("")

        # Industry approach
        industry = comparison['industry_approach']
        lines.append("INDUSTRY BEST PRACTICES:")
        lines.append(f"  Analyzed {industry['num_sources']} authoritative sources")
        if industry['recommended_libraries']:
            lines.append(f"  Common libraries: {', '.join(industry['recommended_libraries'])}")
        if industry['common_patterns']:
            lines.append(f"  Common patterns: {', '.join(industry['common_patterns'])}")
        lines.append("")

        # Recommendations
        if comparison['recommendations']:
            lines.append("RECOMMENDATIONS:")
            for i, rec in enumerate(comparison['recommendations'][:5], 1):
                lines.append(f"\n{i}. {rec['title']}")
                lines.append(f"   {rec['description'][:150]}")
                if rec['code_example']:
                    lines.append("   Example code:")
                    example_lines = rec['code_example'].split('\n')[:5]
                    for ex_line in example_lines:
                        lines.append(f"     {ex_line}")
                    if len(rec['code_example'].split('\n')) > 5:
                        lines.append("     ...")

        return '\n'.join(lines)


if __name__ == "__main__":
    print("Comparison Engine loaded successfully")
