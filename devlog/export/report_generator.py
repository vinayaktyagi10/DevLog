"""
Generate exportable reports from reviews
"""
from typing import Dict
import json
from datetime import datetime


class ReportGenerator:
    """Generate reports in various formats"""

    def generate_markdown(self, review: Dict) -> str:
        """Generate Markdown report"""
        lines = []

        lines.append(f"# Code Review: {review['topic']}\n")
        lines.append(f"**Date**: {review.get('completed_at', '')[:10]}\n")
        lines.append(f"**Commits Analyzed**: {review.get('commits_found', 0)}\n")

        # Your implementation
        lines.append("## Your Implementation\n")
        your_analysis = review.get('your_analysis', {})

        if your_analysis.get('issues'):
            lines.append("### Issues Found\n")
            for issue in your_analysis['issues'][:10]:
                lines.append(f"- {issue}")
            lines.append("")

        # Recommendations
        comparison = review.get('comparison', {})
        if comparison.get('recommendations'):
            lines.append("## Recommendations\n")
            for i, rec in enumerate(comparison['recommendations'][:10], 1):
                lines.append(f"### {i}. {rec['title']}\n")
                lines.append(f"{rec['description']}\n")
                if rec.get('code_example'):
                    lines.append("```")
                    lines.append(rec['code_example'][:500])
                    lines.append("```\n")

        return '\n'.join(lines)

    def generate_json(self, review: Dict) -> str:
        """Generate JSON report"""
        return json.dumps(review, indent=2)

    def save_report(self, review: Dict, filepath: str, format: str = 'markdown'):
        """Save report to file"""
        if format == 'markdown':
            content = self.generate_markdown(review)
        elif format == 'json':
            content = self.generate_json(review)
        else:
            raise ValueError(f"Unsupported format: {format}")

        with open(filepath, 'w') as f:
            f.write(content)
