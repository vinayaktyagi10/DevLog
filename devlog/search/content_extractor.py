"""
Content Extractor - Extract code examples and best practices from scraped content
"""
import re
from typing import List, Dict
from devlog.core.git_ops import detect_language


class ContentExtractor:
    """Extract structured information from scraped web content"""

    def __init__(self):
        self.best_practice_keywords = [
            'best practice', 'recommended', 'should', 'must', 'avoid',
            'always', 'never', 'important', 'security', 'performance',
            'tip:', 'note:', 'warning:', 'caution:'
        ]

    def extract_code_examples(self, content: Dict) -> List[Dict]:
        """
        Extract code examples from scraped content

        Args:
            content: Scraped content dictionary

        Returns:
            List of code examples with metadata
        """
        examples = []
        code_blocks = content.get('code_blocks', [])

        for i, code in enumerate(code_blocks):
            # Skip very short blocks (likely inline code)
            if len(code.strip()) < 30:
                continue

            # Detect language
            language = self._detect_code_language(code)

            # Extract context (text before code block)
            context = self._extract_context(content, i)

            # Determine if it's a best practice example
            is_best_practice = self._is_best_practice(context)

            examples.append({
                'code': code.strip(),
                'language': language,
                'context': context,
                'is_best_practice': is_best_practice,
                'source_url': content.get('url', ''),
                'source_type': content.get('source_type', ''),
            })

        return examples

    def extract_best_practices(self, content: Dict) -> List[str]:
        """
        Extract best practice statements from content

        Args:
            content: Scraped content dictionary

        Returns:
            List of best practice statements
        """
        practices = []
        text = content.get('content', '')

        # Split into sentences
        sentences = re.split(r'[.!?]\s+', text)

        for sentence in sentences:
            sentence = sentence.strip()

            # Check if sentence contains best practice keywords
            if self._is_best_practice(sentence):
                # Clean up the sentence
                if len(sentence) > 20 and len(sentence) < 300:
                    practices.append(sentence)

        # For Stack Overflow, extract from top voted answer
        if content.get('source_type') == 'stackoverflow' and content.get('accepted_answer'):
            answer_text = content['accepted_answer'].get('text', '')
            answer_sentences = re.split(r'[.!?]\s+', answer_text)

            for sentence in answer_sentences[:10]:  # First 10 sentences
                sentence = sentence.strip()
                if len(sentence) > 20 and len(sentence) < 300:
                    if not sentence in practices:  # Avoid duplicates
                        practices.append(sentence)

        return practices[:10]  # Top 10 practices

    def extract_explanations(self, content: Dict) -> str:
        """
        Extract key explanations from content

        Args:
            content: Scraped content dictionary

        Returns:
            Condensed explanation text
        """
        text = content.get('content', '')

        # For Stack Overflow, prefer accepted answer
        if content.get('source_type') == 'stackoverflow' and content.get('accepted_answer'):
            text = content['accepted_answer'].get('text', '')

        # Take first 500 characters (main explanation)
        explanation = text[:500].strip()

        # Try to end at a sentence boundary
        last_period = explanation.rfind('.')
        if last_period > 200:  # If there's a reasonable sentence
            explanation = explanation[:last_period + 1]

        return explanation

    def extract_recommendations(self, content: Dict, topic: str = None) -> List[Dict]:
        """
        Extract actionable recommendations

        Args:
            content: Scraped content dictionary
            topic: Optional topic to focus on

        Returns:
            List of recommendations with reasoning
        """
        recommendations = []
        text = content.get('content', '')

        # Patterns for recommendations
        patterns = [
            r'((?:should|must|need to|have to|recommend)[^.!?]{20,200}[.!?])',
            r'((?:use|implement|add|include|ensure)[^.!?]{20,200}[.!?])',
            r'((?:avoid|don\'t|never|stop)[^.!?]{20,200}[.!?])',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                recommendation = match.strip()

                # Check relevance to topic if provided
                if topic and topic.lower() not in recommendation.lower():
                    continue

                if len(recommendation) > 30 and len(recommendation) < 300:
                    recommendations.append({
                        'text': recommendation,
                        'source_url': content.get('url', ''),
                        'votes': content.get('votes', 0)
                    })

        # Sort by votes (if available) and deduplicate
        seen = set()
        unique_recommendations = []
        for rec in sorted(recommendations, key=lambda x: x['votes'], reverse=True):
            if rec['text'] not in seen:
                seen.add(rec['text'])
                unique_recommendations.append(rec)

        return unique_recommendations[:10]

    def _detect_code_language(self, code: str) -> str:
        """Detect programming language from code snippet"""
        # Simple heuristics
        if 'import ' in code or 'def ' in code or 'class ' in code:
            return 'python'
        elif 'function' in code or 'const ' in code or 'let ' in code or '=>' in code:
            return 'javascript'
        elif 'public class' in code or 'private ' in code or 'System.out' in code:
            return 'java'
        elif '#include' in code or 'int main' in code:
            return 'c'
        elif 'func ' in code or 'package main' in code:
            return 'go'
        else:
            return 'unknown'

    def _extract_context(self, content: Dict, code_index: int) -> str:
        """Extract text context around a code block"""
        text = content.get('content', '')

        # For Stack Overflow, try to get context from answer
        if content.get('source_type') == 'stackoverflow':
            if content.get('accepted_answer'):
                text = content['accepted_answer'].get('text', '')

        # Split into sentences and take a few before code block
        sentences = re.split(r'[.!?]\s+', text)

        # Take up to 3 sentences as context
        if len(sentences) > 3:
            context = '. '.join(sentences[:3])
        else:
            context = '. '.join(sentences)

        return context[:200]  # Limit length

    def _is_best_practice(self, text: str) -> bool:
        """Check if text describes a best practice"""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.best_practice_keywords)

    def normalize_code(self, code: str, language: str) -> str:
        """
        Normalize code formatting

        Args:
            code: Raw code string
            language: Programming language

        Returns:
            Normalized code
        """
        # Remove extra whitespace
        lines = [line.rstrip() for line in code.split('\n')]

        # Remove empty lines at start and end
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()

        return '\n'.join(lines)

    def extract_summary(self, contents: List[Dict], topic: str) -> str:
        """
        Generate a summary from multiple scraped contents

        Args:
            contents: List of scraped content dictionaries
            topic: Topic being researched

        Returns:
            Summary text
        """
        # Collect all best practices
        all_practices = []
        for content in contents:
            practices = self.extract_best_practices(content)
            all_practices.extend(practices)

        # Collect key recommendations
        all_recommendations = []
        for content in contents:
            recs = self.extract_recommendations(content, topic)
            all_recommendations.extend(recs)

        # Build summary
        summary_parts = [
            f"Research summary for '{topic}':",
            f"\nFound {len(contents)} authoritative sources",
        ]

        if all_practices:
            summary_parts.append(f"\nKey best practices ({len(all_practices)}):")
            for i, practice in enumerate(all_practices[:5], 1):
                summary_parts.append(f"  {i}. {practice[:100]}...")

        if all_recommendations:
            summary_parts.append(f"\nTop recommendations ({len(all_recommendations)}):")
            for i, rec in enumerate(all_recommendations[:5], 1):
                summary_parts.append(f"  {i}. {rec['text'][:100]}...")

        return '\n'.join(summary_parts)


def test_extractor():
    """Test the content extractor"""
    extractor = ContentExtractor()

    # Sample content
    sample_content = {
        'url': 'https://example.com',
        'source_type': 'blog',
        'content': '''
        When implementing JWT authentication, you should always use HTTPS.
        Never store sensitive data in the JWT payload as it's only base64 encoded.
        Best practice is to use short expiration times, typically 15-60 minutes.
        You must validate the signature on every request.
        ''',
        'code_blocks': [
            '''
import jwt
from datetime import datetime, timedelta

def create_token(user_id):
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(minutes=15)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')
            '''
        ]
    }

    print("Testing Content Extractor...")

    # Extract best practices
    practices = extractor.extract_best_practices(sample_content)
    print(f"\nBest Practices Found: {len(practices)}")
    for p in practices:
        print(f"  • {p}")

    # Extract code examples
    examples = extractor.extract_code_examples(sample_content)
    print(f"\nCode Examples Found: {len(examples)}")
    for ex in examples:
        print(f"  • Language: {ex['language']}")
        print(f"    Lines: {len(ex['code'].splitlines())}")
        print(f"    Best practice: {ex['is_best_practice']}")


if __name__ == "__main__":
    test_extractor()
