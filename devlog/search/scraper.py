"""
Web Scraper - Extract content from technical websites
"""
import httpx
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
import time
from urllib.parse import urlparse
import re


class WebScraper:
    """Scrape and extract content from technical websites"""

    def __init__(self):
        self.user_agent = "DevLog/1.0 (Code Review Assistant; +https://github.com/yourusername/devlog)"
        self.rate_limit_delay = 1.0  # seconds between requests
        self.last_request_time = {}
        self.cache = {}

    def scrape_url(self, url: str, timeout: int = 10) -> Optional[Dict]:
        """
        Scrape content from a URL

        Args:
            url: URL to scrape
            timeout: Request timeout in seconds

        Returns:
            Dictionary with extracted content or None if failed
        """
        # Check cache
        if url in self.cache:
            return self.cache[url]

        # Rate limiting
        domain = urlparse(url).netloc
        self._apply_rate_limit(domain)

        try:
            response = httpx.get(
                url,
                headers={"User-Agent": self.user_agent},
                timeout=timeout,
                follow_redirects=True
            )

            if response.status_code != 200:
                print(f"Failed to fetch {url}: HTTP {response.status_code}")
                return None

            # Parse HTML
            soup = BeautifulSoup(response.text, 'lxml')

            # Extract based on site type
            if 'stackoverflow.com' in url:
                content = self._extract_stackoverflow(soup, url)
            elif 'github.com' in url:
                content = self._extract_github(soup, url)
            elif any(doc_site in url for doc_site in ['python.org', 'nodejs.org', 'mozilla.org']):
                content = self._extract_documentation(soup, url)
            elif any(blog in url for blog in ['dev.to', 'medium.com']):
                content = self._extract_blog_post(soup, url)
            else:
                # Generic extraction
                content = self._extract_generic(soup, url)

            # Cache result
            if content:
                self.cache[url] = content

            return content

        except httpx.TimeoutException:
            print(f"Timeout scraping {url}")
            return None
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return None

    def _apply_rate_limit(self, domain: str):
        """Apply rate limiting per domain"""
        if domain in self.last_request_time:
            elapsed = time.time() - self.last_request_time[domain]
            if elapsed < self.rate_limit_delay:
                time.sleep(self.rate_limit_delay - elapsed)

        self.last_request_time[domain] = time.time()

    def _extract_stackoverflow(self, soup: BeautifulSoup, url: str) -> Dict:
        """Extract content from Stack Overflow answers"""
        content = {
            'url': url,
            'source_type': 'stackoverflow',
            'title': '',
            'question': '',
            'accepted_answer': None,
            'top_answers': [],
            'code_blocks': [],
            'votes': 0
        }

        # Title
        title_elem = soup.find('h1', class_='fs-headline1')
        if title_elem:
            content['title'] = title_elem.get_text(strip=True)

        # Question
        question_elem = soup.find('div', class_='s-prose js-post-body')
        if question_elem:
            content['question'] = question_elem.get_text(strip=True)[:500]

        # Answers
        answers = soup.find_all('div', class_='answer')

        for answer in answers[:3]:  # Top 3 answers
            answer_data = {}

            # Vote count
            vote_elem = answer.find('div', {'data-value': True})
            if vote_elem:
                try:
                    answer_data['votes'] = int(vote_elem['data-value'])
                except:
                    answer_data['votes'] = 0

            # Answer text
            answer_body = answer.find('div', class_='s-prose js-post-body')
            if answer_body:
                answer_data['text'] = answer_body.get_text(strip=True)[:1000]

                # Extract code blocks from answer
                code_blocks = answer_body.find_all('code')
                answer_data['code_blocks'] = [
                    code.get_text() for code in code_blocks if len(code.get_text()) > 20
                ]

            # Check if accepted
            if answer.find('div', class_='accepted-answer-indicator'):
                content['accepted_answer'] = answer_data
                content['votes'] = answer_data.get('votes', 0)
            else:
                content['top_answers'].append(answer_data)

            # Collect all code blocks
            content['code_blocks'].extend(answer_data.get('code_blocks', []))

        return content

    def _extract_github(self, soup: BeautifulSoup, url: str) -> Dict:
        """Extract content from GitHub (README, code files)"""
        content = {
            'url': url,
            'source_type': 'github',
            'title': '',
            'content': '',
            'code_blocks': []
        }

        # Repository README
        readme = soup.find('article', class_='markdown-body')
        if readme:
            content['content'] = readme.get_text(strip=True)[:2000]

            # Extract code blocks
            code_blocks = readme.find_all('pre')
            content['code_blocks'] = [
                code.get_text() for code in code_blocks if len(code.get_text()) > 20
            ]

        # Repository title
        title_elem = soup.find('strong', itemprop='name')
        if title_elem:
            content['title'] = title_elem.get_text(strip=True)

        return content

    def _extract_documentation(self, soup: BeautifulSoup, url: str) -> Dict:
        """Extract content from official documentation"""
        content = {
            'url': url,
            'source_type': 'documentation',
            'title': '',
            'content': '',
            'code_blocks': []
        }

        # Title
        title_elem = soup.find('h1') or soup.find('title')
        if title_elem:
            content['title'] = title_elem.get_text(strip=True)

        # Main content (try common doc structures)
        main_content = (
            soup.find('main') or
            soup.find('article') or
            soup.find('div', class_='document') or
            soup.find('div', {'role': 'main'})
        )

        if main_content:
            # Remove navigation and sidebars
            for nav in main_content.find_all(['nav', 'aside']):
                nav.decompose()

            content['content'] = main_content.get_text(strip=True)[:3000]

            # Extract code blocks
            code_blocks = main_content.find_all(['pre', 'code'])
            content['code_blocks'] = [
                code.get_text() for code in code_blocks if len(code.get_text()) > 20
            ]

        return content

    def _extract_blog_post(self, soup: BeautifulSoup, url: str) -> Dict:
        """Extract content from blog posts (dev.to, medium, etc.)"""
        content = {
            'url': url,
            'source_type': 'blog',
            'title': '',
            'content': '',
            'code_blocks': []
        }

        # Title
        title_elem = soup.find('h1')
        if title_elem:
            content['title'] = title_elem.get_text(strip=True)

        # Content (try common blog structures)
        main_content = (
            soup.find('article') or
            soup.find('div', class_='post-content') or
            soup.find('div', {'role': 'main'})
        )

        if main_content:
            content['content'] = main_content.get_text(strip=True)[:2000]

            # Extract code blocks
            code_blocks = main_content.find_all('pre')
            content['code_blocks'] = [
                code.get_text() for code in code_blocks if len(code.get_text()) > 20
            ]

        return content

    def _extract_generic(self, soup: BeautifulSoup, url: str) -> Dict:
        """Generic extraction for unknown sites"""
        content = {
            'url': url,
            'source_type': 'generic',
            'title': '',
            'content': '',
            'code_blocks': []
        }

        # Title
        title_elem = soup.find('title') or soup.find('h1')
        if title_elem:
            content['title'] = title_elem.get_text(strip=True)

        # Try to find main content
        main_content = soup.find('main') or soup.find('article') or soup.find('body')

        if main_content:
            # Remove scripts, styles, nav
            for tag in main_content.find_all(['script', 'style', 'nav', 'header', 'footer']):
                tag.decompose()

            content['content'] = main_content.get_text(strip=True)[:2000]

            # Extract code blocks
            code_blocks = main_content.find_all(['pre', 'code'])
            content['code_blocks'] = [
                code.get_text() for code in code_blocks if len(code.get_text()) > 20
            ]

        return content

    def score_content_quality(self, content: Dict) -> float:
        """
        Score content quality (0.0 - 1.0)

        Based on:
        - Source type authority
        - Content length
        - Code examples present
        - Votes (if available)
        """
        score = 0.5  # Base score

        # Source type bonus
        source_scores = {
            'documentation': 0.3,
            'stackoverflow': 0.25,
            'github': 0.2,
            'blog': 0.15,
            'generic': 0.1
        }
        score += source_scores.get(content.get('source_type'), 0.1)

        # Content length bonus (good content is detailed)
        content_length = len(content.get('content', ''))
        if content_length > 1000:
            score += 0.1
        elif content_length > 500:
            score += 0.05

        # Code examples bonus
        if content.get('code_blocks'):
            score += 0.1
            if len(content['code_blocks']) >= 3:
                score += 0.05

        # Votes bonus (Stack Overflow)
        votes = content.get('votes', 0)
        if votes > 100:
            score += 0.1
        elif votes > 50:
            score += 0.05

        return min(score, 1.0)

    def scrape_multiple(self, urls: List[str], max_workers: int = 3) -> List[Dict]:
        """
        Scrape multiple URLs with rate limiting

        Args:
            urls: List of URLs to scrape
            max_workers: Not used (sequential to respect rate limits)

        Returns:
            List of scraped content dictionaries
        """
        results = []

        for url in urls:
            content = self.scrape_url(url)
            if content:
                content['quality_score'] = self.score_content_quality(content)
                results.append(content)

        return results


def test_scraper():
    """Test the scraper"""
    scraper = WebScraper()

    # Test Stack Overflow
    print("Testing Stack Overflow scraping...")
    so_url = "https://stackoverflow.com/questions/11625839/what-is-the-difference-between-jwt-and-oauth-authentication"
    content = scraper.scrape_url(so_url)

    if content:
        print(f"✓ Title: {content['title'][:80]}...")
        print(f"✓ Answers: {len(content['top_answers'])}")
        print(f"✓ Code blocks: {len(content['code_blocks'])}")
        print(f"✓ Quality score: {scraper.score_content_quality(content):.2f}")
    else:
        print("✗ Scraping failed")


if __name__ == "__main__":
    test_scraper()
