"""
DevLog Code Analyzer - AI-powered code analysis
"""
import json
from typing import Dict, List, Optional
from datetime import datetime
import sqlite3
from devlog.paths import DB_PATH


class CodeAnalyzer:
    """Analyzes code and generates improvement suggestions"""

    def __init__(self):
        self.analysis_types = {
            'quick': self._quick_analysis,
            'deep': self._deep_analysis,
            'patterns': self._pattern_analysis,
        }

    async def analyze_commit(self, commit_hash: str, analysis_type: str = 'quick', context: Optional[str] = None) -> Optional[Dict]:
        """
        Analyze a specific commit

        Args:
            commit_hash: Git commit hash (short or full)
            analysis_type: 'quick', 'deep', or 'patterns'
            context: Optional context to improve analysis (e.g., best practices)

        Returns:
            Analysis results or None if commit not found
        """
        # Get commit details from database
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT
                c.id,
                c.commit_hash,
                c.short_hash,
                c.message,
                c.author,
                c.timestamp,
                r.repo_name
            FROM git_commits c
            JOIN tracked_repos r ON c.repo_id = r.id
            WHERE c.commit_hash LIKE ? OR c.short_hash = ?
        """, (f"{commit_hash}%", commit_hash))

        commit = c.fetchone()
        if not commit:
            conn.close()
            return None

        commit_id = commit['id']

        # Get code changes
        c.execute("""
            SELECT
                file_path,
                change_type,
                language,
                diff_text,
                code_after,
                lines_added,
                lines_removed
            FROM code_changes
            WHERE commit_id = ?
        """, (commit_id,))

        changes = [dict(row) for row in c.fetchall()]
        conn.close()

        # Check cache first (skip cache if context is provided, as it modifies the analysis)
        if not context:
            cached = self._get_cached_analysis(commit_id, analysis_type)
            if cached:
                return cached

        # Perform analysis
        analyzer_func = self.analysis_types.get(analysis_type, self._quick_analysis)
        
        # Pass context if the analyzer function supports it (quick and deep do)
        if analysis_type in ['quick', 'deep']:
            result = await analyzer_func(commit, changes, context)
        else:
            result = await analyzer_func(commit, changes)

        # Cache the result (only if generic, context-specific analysis shouldn't overwrite generic cache)
        if not context:
            self._cache_analysis(commit_id, analysis_type, result)

        return result

    async def analyze_file(self, file_path: str, code: str, language: str) -> Dict:
        """
        Analyze current state of a file

        Args:
            file_path: Path to file
            code: Current code content
            language: Programming language

        Returns:
            Analysis results
        """
        # Build analysis context
        context = {
            'file_path': file_path,
            'language': language,
            'code': code,
            'lines': len(code.splitlines())
        }

        # Generate analysis prompt
        from devlog.analysis.llm import analyze_code

        prompt = self._build_file_analysis_prompt(context)
        analysis_text = await analyze_code(prompt, code, language)

        # Parse and structure the response
        result = self._parse_analysis_response(analysis_text)
        result['file_path'] = file_path
        result['language'] = language
        result['analyzed_at'] = datetime.now().isoformat()

        return result

    async def batch_analyze(self, repo_name: str, limit: int = 10) -> List[Dict]:
        """
        Analyze last N commits in a repository

        Args:
            repo_name: Repository name
            limit: Number of commits to analyze

        Returns:
            List of analysis results
        """
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT c.short_hash
            FROM git_commits c
            JOIN tracked_repos r ON c.repo_id = r.id
            WHERE r.repo_name LIKE ? AND r.active = 1
            ORDER BY c.timestamp DESC
            LIMIT ?
        """, (f"%{repo_name}%", limit))

        commits = [row['short_hash'] for row in c.fetchall()]
        conn.close()

        results = []
        for commit_hash in commits:
            analysis = await self.analyze_commit(commit_hash, 'quick')
            if analysis:
                results.append(analysis)

        return results

    async def _quick_analysis(self, commit: Dict, changes: List[Dict], context_str: Optional[str] = None) -> Dict:
        """Quick analysis: summary + immediate issues"""
        from devlog.analysis.llm import analyze_code

        # Build context
        context = {
            'commit_message': commit['message'],
            'files_changed': len(changes),
            'languages': list(set(c['language'] for c in changes if c['language'])),
            'total_lines_added': sum(c['lines_added'] for c in changes),
            'total_lines_removed': sum(c['lines_removed'] for c in changes),
        }

        # Analyze each changed file
        issues = []
        suggestions = []

        for change in changes[:5]:  # Limit to 5 files for quick analysis
            if not change['code_after'] or change['language'] not in ['python', 'javascript', 'typescript', 'java']:
                continue

            prompt = self._build_quick_prompt(change, commit['message'], context_str)
            analysis_text = await analyze_code(prompt, change['code_after'], change['language'])

            parsed = self._parse_analysis_response(analysis_text)
            issues.extend(parsed.get('issues', []))
            suggestions.extend(parsed.get('suggestions', []))

        return {
            'commit_hash': commit['short_hash'],
            'repo_name': commit['repo_name'],
            'analysis_type': 'quick',
            'summary': f"Analyzed {len(changes)} files with {context['total_lines_added']} additions and {context['total_lines_removed']} deletions",
            'issues': issues[:10],  # Top 10 issues
            'suggestions': suggestions[:10],  # Top 10 suggestions
            'context': context,
            'analyzed_at': datetime.now().isoformat()
        }

    async def _deep_analysis(self, commit: Dict, changes: List[Dict], context_str: Optional[str] = None) -> Dict:
        """Deep analysis: patterns, anti-patterns, complexity"""
        from devlog.analysis.llm import analyze_code

        patterns_found = []
        anti_patterns = []
        complexity_issues = []
        quality_score = 0

        for change in changes:
            if not change['code_after'] or change['language'] not in ['python', 'javascript', 'typescript', 'java']:
                continue

            prompt = self._build_deep_prompt(change, context_str)
            analysis_text = await analyze_code(prompt, change['code_after'], change['language'])

            parsed = self._parse_deep_analysis(analysis_text)
            patterns_found.extend(parsed.get('patterns', []))
            anti_patterns.extend(parsed.get('anti_patterns', []))
            complexity_issues.extend(parsed.get('complexity', []))

        # Calculate quality score (0-100)
        quality_score = self._calculate_quality_score(patterns_found, anti_patterns, complexity_issues)

        return {
            'commit_hash': commit['short_hash'],
            'repo_name': commit['repo_name'],
            'analysis_type': 'deep',
            'summary': f"Deep analysis found {len(patterns_found)} patterns and {len(anti_patterns)} anti-patterns",
            'patterns': patterns_found,
            'anti_patterns': anti_patterns,
            'complexity_issues': complexity_issues,
            'quality_score': quality_score,
            'analyzed_at': datetime.now().isoformat()
        }

    async def _pattern_analysis(self, commit: Dict, changes: List[Dict]) -> Dict:
        """Pattern analysis: detect coding patterns and habits"""
        from devlog.analysis.llm import analyze_code

        patterns = {
            'design_patterns': [],
            'code_style': [],
            'common_practices': [],
            'repetitive_code': []
        }

        for change in changes:
            if not change['code_after']:
                continue

            prompt = self._build_pattern_prompt(change)
            analysis_text = await analyze_code(prompt, change['code_after'], change['language'])

            parsed = self._parse_pattern_analysis(analysis_text)
            for key in patterns:
                patterns[key].extend(parsed.get(key, []))

        return {
            'commit_hash': commit['short_hash'],
            'repo_name': commit['repo_name'],
            'analysis_type': 'patterns',
            'summary': f"Pattern analysis identified {sum(len(v) for v in patterns.values())} patterns",
            'patterns': patterns,
            'analyzed_at': datetime.now().isoformat()
        }

    def _build_quick_prompt(self, change: Dict, commit_message: str, context: Optional[str] = None) -> str:
        """Build prompt for quick analysis"""
        prompt = f"""Analyze this code change and identify immediate issues and quick improvements.

Commit message: {commit_message}
File: {change['file_path']}
Language: {change['language']}
Changes: +{change['lines_added']} -{change['lines_removed']}
"""
        if context:
            prompt += f"\n{context}\n"

        prompt += """
Focus on:
1. Potential bugs or errors
2. Security vulnerabilities
3. Performance issues
4. Quick wins for improvement

Provide response in this format:
ISSUES:
- [issue description]

SUGGESTIONS:
- [specific actionable suggestion]

Keep it concise and actionable."""
        return prompt

    def _build_deep_prompt(self, change: Dict, context: Optional[str] = None) -> str:
        """Build prompt for deep analysis"""
        prompt = f"""Perform a deep code analysis focusing on design patterns, anti-patterns, and complexity.

File: {change['file_path']}
Language: {change['language']}
"""
        if context:
            prompt += f"\n{context}\n"

        prompt += """
Analyze:
1. Design patterns used (factory, singleton, observer, etc.)
2. Anti-patterns present (god object, spaghetti code, etc.)
3. Code complexity (cyclomatic, cognitive)
4. Maintainability concerns

Provide response in this format:
PATTERNS:
- [pattern name]: [description]

ANTI-PATTERNS:
- [anti-pattern name]: [description and impact]

COMPLEXITY:
- [complexity issue and recommendation]"""
        return prompt

    def _build_pattern_prompt(self, change: Dict) -> str:
        """Build prompt for pattern analysis"""
        return f"""Analyze coding patterns and practices in this code.

File: {change['file_path']}
Language: {change['language']}

Identify:
1. Design patterns being used
2. Code style preferences (naming, structure)
3. Common practices (error handling, logging, etc.)
4. Repetitive code that could be refactored

Provide response in this format:
DESIGN_PATTERNS:
- [pattern description]

CODE_STYLE:
- [style observation]

COMMON_PRACTICES:
- [practice description]

REPETITIVE_CODE:
- [location and suggestion]"""

    def _build_file_analysis_prompt(self, context: Dict) -> str:
        """Build prompt for file analysis"""
        return f"""Analyze this entire file and provide comprehensive feedback.

File: {context['file_path']}
Language: {context['language']}
Lines: {context['lines']}

Provide:
1. Overall code quality assessment
2. Main issues to address
3. Specific improvement suggestions
4. Best practices not being followed

Format as:
ASSESSMENT:
[overall quality assessment]

ISSUES:
- [issue description]

SUGGESTIONS:
- [specific suggestion with code example if relevant]"""

    def _parse_analysis_response(self, text: str) -> Dict:
        """Parse LLM response into structured data"""
        result = {
            'issues': [],
            'suggestions': [],
            'raw_response': text
        }

        current_section = None
        for line in text.split('\n'):
            line = line.strip()

            if line.startswith('ISSUES:'):
                current_section = 'issues'
            elif line.startswith('SUGGESTIONS:'):
                current_section = 'suggestions'
            elif line.startswith('-') and current_section:
                item = line[1:].strip()
                if item:
                    result[current_section].append(item)

        return result

    def _parse_deep_analysis(self, text: str) -> Dict:
        """Parse deep analysis response"""
        result = {
            'patterns': [],
            'anti_patterns': [],
            'complexity': []
        }

        current_section = None
        for line in text.split('\n'):
            line = line.strip()

            if 'PATTERNS:' in line:
                current_section = 'patterns'
            elif 'ANTI-PATTERNS:' in line or 'ANTIPATTERNS:' in line:
                current_section = 'anti_patterns'
            elif 'COMPLEXITY:' in line:
                current_section = 'complexity'
            elif line.startswith('-') and current_section:
                item = line[1:].strip()
                if item:
                    result[current_section].append(item)

        return result

    def _parse_pattern_analysis(self, text: str) -> Dict:
        """Parse pattern analysis response"""
        result = {
            'design_patterns': [],
            'code_style': [],
            'common_practices': [],
            'repetitive_code': []
        }

        current_section = None
        section_map = {
            'DESIGN_PATTERNS:': 'design_patterns',
            'CODE_STYLE:': 'code_style',
            'COMMON_PRACTICES:': 'common_practices',
            'REPETITIVE_CODE:': 'repetitive_code'
        }

        for line in text.split('\n'):
            line = line.strip()

            for key, section in section_map.items():
                if key in line:
                    current_section = section
                    break

            if line.startswith('-') and current_section:
                item = line[1:].strip()
                if item:
                    result[current_section].append(item)

        return result

    def _calculate_quality_score(self, patterns: List, anti_patterns: List, complexity: List) -> int:
        """Calculate code quality score 0-100"""
        score = 70  # Base score

        # Positive: good patterns found
        score += min(len(patterns) * 5, 20)

        # Negative: anti-patterns found
        score -= min(len(anti_patterns) * 10, 40)

        # Negative: complexity issues
        score -= min(len(complexity) * 5, 20)

        return max(0, min(100, score))

    def _get_cached_analysis(self, commit_id: int, analysis_type: str) -> Optional[Dict]:
        """Retrieve cached analysis from database"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT summary, issues, suggestions, patterns, analyzed_at
            FROM analyses
            WHERE commit_id = ? AND analysis_type = ?
            ORDER BY analyzed_at DESC
            LIMIT 1
        """, (commit_id, analysis_type))

        result = c.fetchone()
        conn.close()

        if result:
            return {
                'summary': result['summary'],
                'issues': json.loads(result['issues']) if result['issues'] else [],
                'suggestions': json.loads(result['suggestions']) if result['suggestions'] else [],
                'patterns': json.loads(result['patterns']) if result['patterns'] else [],
                'analyzed_at': result['analyzed_at'],
                'cached': True
            }

        return None

    def _cache_analysis(self, commit_id: int, analysis_type: str, result: Dict):
        """Store analysis in database cache"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("""
            INSERT INTO analyses (
                commit_id, analysis_type, summary, issues, suggestions, patterns, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            commit_id,
            analysis_type,
            result.get('summary', ''),
            json.dumps(result.get('issues', [])),
            json.dumps(result.get('suggestions', [])),
            json.dumps(result.get('patterns', {})),
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()
