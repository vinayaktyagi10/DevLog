"""
Deep Search - Full-text + Semantic + Code Content Search

Provides 3 search modes:
1. Keyword search (fast, metadata only)
2. Code content search (searches actual code)
3. Semantic search (understands meaning via embeddings)
"""

import sqlite3
from typing import List, Dict, Optional
from devlog.paths import DB_PATH
from devlog.core.embeddings import semantic_search as embeddings_semantic_search, generate_embedding
from devlog.core.code_extract import extract_functions_from_code
import re


class DeepSearch:
    """Advanced search combining multiple strategies"""

    def __init__(self):
        self.conn = None

    def _get_connection(self):
        """Get database connection"""
        if not self.conn:
            self.conn = sqlite3.connect(DB_PATH)
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

    # ==================== KEYWORD SEARCH ====================

    def keyword_search(
        self,
        query: str,
        repo_filter: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Fast keyword search in commit messages and file paths"""
        conn = self._get_connection()
        c = conn.cursor()

        where_clauses = ["r.active = 1"]
        params = []

        if query:
            where_clauses.append("(c.message LIKE ? OR cc.file_path LIKE ?)")
            search_term = f"%{query}%"
            params.extend([search_term, search_term])

        if repo_filter:
            where_clauses.append("r.repo_name LIKE ?")
            params.append(f"%{repo_filter}%")

        if language:
            where_clauses.append("cc.language = ?")
            params.append(language)

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT DISTINCT
                c.id as commit_id,
                c.commit_hash,
                c.short_hash,
                c.message,
                c.author,
                c.timestamp,
                c.branch,
                c.files_changed,
                c.insertions,
                c.deletions,
                r.repo_name,
                r.repo_path,
                'keyword' as match_type,
                0.6 as score
            FROM git_commits c
            JOIN tracked_repos r ON c.repo_id = r.id
            LEFT JOIN code_changes cc ON c.id = cc.commit_id
            WHERE {where_sql}
            ORDER BY c.timestamp DESC
            LIMIT ?
        """

        params.append(limit)
        c.execute(sql, params)
        results = [dict(row) for row in c.fetchall()]

        # Attach file details
        for result in results:
            c.execute("""
                SELECT file_path, change_type, language, lines_added, lines_removed
                FROM code_changes
                WHERE commit_id = ?
            """, (result['commit_id'],))
            result['files'] = [dict(row) for row in c.fetchall()]

        return results

    # ==================== CODE CONTENT SEARCH ====================

    def code_search(
        self,
        query: str,
        repo_filter: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Search within actual code content (code_after, diff_text)"""
        conn = self._get_connection()
        c = conn.cursor()

        where_clauses = ["r.active = 1"]
        params = []

        # Search in code content or diff
        if query:
            where_clauses.append(
                "(cc.code_after LIKE ? OR cc.diff_text LIKE ?)"
            )
            search_term = f"%{query}%"
            params.extend([search_term, search_term])

        if repo_filter:
            where_clauses.append("r.repo_name LIKE ?")
            params.append(f"%{repo_filter}%")

        if language:
            where_clauses.append("cc.language = ?")
            params.append(language)

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT DISTINCT
                c.id as commit_id,
                c.commit_hash,
                c.short_hash,
                c.message,
                c.author,
                c.timestamp,
                c.branch,
                c.files_changed,
                r.repo_name,
                cc.file_path,
                cc.language,
                cc.code_after,
                'code_content' as match_type,
                1.0 as score
            FROM git_commits c
            JOIN tracked_repos r ON c.repo_id = r.id
            JOIN code_changes cc ON c.id = cc.commit_id
            WHERE {where_sql}
            ORDER BY c.timestamp DESC
            LIMIT ?
        """

        params.append(limit)
        c.execute(sql, params)
        results = [dict(row) for row in c.fetchall()]

        # Extract snippets and group by commit
        for result in results:
            result['code_snippet'] = self._extract_code_snippet(
                result.get('code_after', ''),
                query
            )
            result.pop('code_after', None)

        return self._group_by_commit(results)

    # ==================== SEMANTIC SEARCH ====================

    def semantic_search_commits(
        self,
        query: str,
        repo_filter: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """Semantic search using embeddings"""
        try:
            results = embeddings_semantic_search(query, limit=limit * 2)

            # Filter by repo
            if repo_filter:
                results = [
                    r for r in results
                    if repo_filter.lower() in r.get('repo_name', '').lower()
                ]

            # Format results
            formatted = []
            for result in results[:limit]:
                formatted.append({
                    'commit_id': result['id'],
                    'commit_hash': result['commit_hash'],
                    'short_hash': result['short_hash'],
                    'message': result['message'],
                    'timestamp': result['timestamp'],
                    'repo_name': result['repo_name'],
                    'match_type': 'semantic',
                    'score': result.get('similarity', 0.5) * 1.5,
                    'files': []
                })

            return formatted
        except Exception as e:
            print(f"Semantic search error: {e}")
            return []

    # ==================== FUNCTION SEARCH ====================

    def function_search(
        self,
        function_name: str,
        repo_filter: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 30
    ) -> List[Dict]:
        """Search for specific function/class names"""
        conn = self._get_connection()
        c = conn.cursor()

        where_clauses = ["r.active = 1", "cc.code_after IS NOT NULL"]
        params = []

        if repo_filter:
            where_clauses.append("r.repo_name LIKE ?")
            params.append(f"%{repo_filter}%")

        if language:
            where_clauses.append("cc.language = ?")
            params.append(language)
        else:
            where_clauses.append("cc.language IN ('python', 'javascript', 'typescript', 'java', 'go', 'c', 'cpp')")

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                c.id as commit_id,
                c.short_hash,
                c.message,
                c.timestamp,
                r.repo_name,
                cc.file_path,
                cc.language,
                cc.code_after
            FROM git_commits c
            JOIN tracked_repos r ON c.repo_id = r.id
            JOIN code_changes cc ON c.id = cc.commit_id
            WHERE {where_sql}
            ORDER BY c.timestamp DESC
            LIMIT ?
        """

        params.append(limit * 3)
        c.execute(sql, params)

        results = []
        seen_commits = set()

        for row in c.fetchall():
            row_dict = dict(row)
            code = row_dict.get('code_after', '')
            language = row_dict.get('language', 'python')

            if not code:
                continue

            try:
                functions = extract_functions_from_code(code, language)

                for func in functions:
                    if function_name.lower() in func['name'].lower():
                        commit_id = row_dict['commit_id']

                        if commit_id not in seen_commits:
                            seen_commits.add(commit_id)
                            results.append({
                                'commit_id': commit_id,
                                'short_hash': row_dict['short_hash'],
                                'message': row_dict['message'],
                                'timestamp': row_dict['timestamp'],
                                'repo_name': row_dict['repo_name'],
                                'file_path': row_dict['file_path'],
                                'function_name': func['name'],
                                'code_snippet': func['code'][:300],
                                'match_type': 'function',
                                'score': 0.9,
                                'files': []
                            })

                        if len(results) >= limit:
                            break
            except:
                continue

            if len(results) >= limit:
                break

        return results

    # ==================== UNIFIED SEARCH ====================

    def search_all(
        self,
        query: str,
        repo_filter: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """Unified search combining all methods"""
        all_results = []

        # 1. Keyword search
        all_results.extend(
            self.keyword_search(query, repo_filter, language, limit)
        )

        # 2. Code content search
        all_results.extend(
            self.code_search(query, repo_filter, language, limit)
        )

        # 3. Semantic search (for multi-word queries)
        if len(query.split()) > 2:
            all_results.extend(
                self.semantic_search_commits(query, repo_filter, limit)
            )

        # 4. Function search (if looks like function name)
        func_name = self._extract_function_name(query)
        if func_name:
            all_results.extend(
                self.function_search(func_name, repo_filter, language, limit)
            )

        # Deduplicate and rank
        return self._deduplicate_and_rank(all_results, limit)

    # ==================== HELPER METHODS ====================

    def _extract_code_snippet(self, code: str, query: str, context_lines: int = 2) -> str:
        """Extract snippet around query match"""
        if not code:
            return ""

        lines = code.split('\n')
        query_lower = query.lower()

        for i, line in enumerate(lines):
            if query_lower in line.lower():
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                return '\n'.join(lines[start:end])

        return '\n'.join(lines[:5])

    def _extract_function_name(self, query: str) -> Optional[str]:
        """Extract function name from query"""
        patterns = [
            r'function\s+(\w+)',
            r'method\s+(\w+)',
            r'class\s+(\w+)',
            r'def\s+(\w+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, query.lower())
            if match:
                return match.group(1)

        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', query.strip()):
            return query.strip()

        return None

    def _group_by_commit(self, results: List[Dict]) -> List[Dict]:
        """Group file-level results by commit"""
        commit_map = {}

        for result in results:
            cid = result['commit_id']

            if cid not in commit_map:
                commit_map[cid] = {
                    'commit_id': cid,
                    'commit_hash': result['commit_hash'],
                    'short_hash': result['short_hash'],
                    'message': result['message'],
                    'author': result.get('author', 'unknown'),
                    'timestamp': result['timestamp'],
                    'repo_name': result['repo_name'],
                    'match_type': result['match_type'],
                    'score': result['score'],
                    'files': [],
                    'code_snippets': []
                }

            if 'file_path' in result:
                commit_map[cid]['files'].append({
                    'file_path': result['file_path'],
                    'language': result.get('language', 'unknown')
                })

            if 'code_snippet' in result:
                commit_map[cid]['code_snippets'].append(result['code_snippet'])

        return list(commit_map.values())

    def _deduplicate_and_rank(self, results: List[Dict], limit: int) -> List[Dict]:
        """Deduplicate by commit_id and rank by score"""
        commit_map = {}

        for result in results:
            cid = result['commit_id']

            if cid in commit_map:
                existing = commit_map[cid]
                existing['score'] = max(existing['score'], result['score'])

                # Merge files
                existing_files = {f.get('file_path', '') for f in existing.get('files', [])}
                for file in result.get('files', []):
                    if file.get('file_path', '') not in existing_files:
                        existing['files'].append(file)

                # Merge snippets
                if 'code_snippets' in result:
                    if 'code_snippets' not in existing:
                        existing['code_snippets'] = []
                    existing['code_snippets'].extend(result['code_snippets'])
            else:
                commit_map[cid] = result

        sorted_results = sorted(
            commit_map.values(),
            key=lambda x: x.get('score', 0),
            reverse=True
        )

        return sorted_results[:limit]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ==================== CONVENIENCE FUNCTIONS ====================

def hybrid_search(
    query: str,
    repo_filter: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 20
) -> List[Dict]:
    """Main entry point for hybrid search"""
    with DeepSearch() as searcher:
        return searcher.search_all(query, repo_filter, language, limit)


def search_code_content(
    query: str,
    repo_filter: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 20
) -> List[Dict]:
    """Search code content only"""
    with DeepSearch() as searcher:
        return searcher.code_search(query, repo_filter, language, limit)


def search_function_names(
    query: str,
    repo_filter: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 20
) -> List[Dict]:
    """Search function names only"""
    with DeepSearch() as searcher:
        return searcher.function_search(query, repo_filter, language, limit)


def semantic_search_commits(
    query: str,
    repo_filter: Optional[str] = None,
    limit: int = 20
) -> List[Dict]:
    """Semantic search only"""
    with DeepSearch() as searcher:
        return searcher.semantic_search_commits(query, repo_filter, limit)


def search_in_repo_pattern(
    query: str,
    repo_pattern: str,
    language: Optional[str] = None,
    limit: int = 20
) -> List[Dict]:
    """Search in repos matching pattern"""
    return hybrid_search(query, repo_filter=repo_pattern, language=language, limit=limit)
