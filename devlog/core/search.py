import sqlite3
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from devlog.paths import DB_PATH

def search_commits(
    query: Optional[str] = None,
    repo_name: Optional[str] = None,
    language: Optional[str] = None,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
    limit: int = 50
) -> List[Dict]:
    """
    Search commits with various filters

    Args:
        query: Search in commit message and file paths
        repo_name: Filter by repository name
        language: Filter by programming language
        after_date: ISO format date (YYYY-MM-DD)
        before_date: ISO format date (YYYY-MM-DD)
        limit: Maximum results

    Returns:
        List of matching commits with details
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    c = conn.cursor()

    # Build query dynamically
    where_clauses = ["r.active = 1"]
    params = []

    if query:
        where_clauses.append(
            "(c.message LIKE ? OR cc.file_path LIKE ?)"
        )
        search_term = f"%{query}%"
        params.extend([search_term, search_term])

    if repo_name:
        where_clauses.append("r.repo_name LIKE ?")
        params.append(f"%{repo_name}%")

    if language:
        where_clauses.append("cc.language = ?")
        params.append(language)

    if after_date:
        where_clauses.append("c.timestamp >= ?")
        params.append(after_date)

    if before_date:
        where_clauses.append("c.timestamp <= ?")
        params.append(before_date)

    where_sql = " AND ".join(where_clauses)

    # Main query - get commits with file changes
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
            r.repo_path
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

    # For each commit, get the changed files
    for result in results:
        c.execute("""
            SELECT file_path, change_type, language, lines_added, lines_removed
            FROM code_changes
            WHERE commit_id = ?
        """, (result['commit_id'],))
        result['files'] = [dict(row) for row in c.fetchall()]

    conn.close()
    return results

def get_commit_details(commit_hash: str) -> Optional[Dict]:
    """Get full details for a specific commit"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get commit info
    c.execute("""
        SELECT
            c.*,
            r.repo_name,
            r.repo_path
        FROM git_commits c
        JOIN tracked_repos r ON c.repo_id = r.id
        WHERE c.commit_hash LIKE ? OR c.short_hash = ?
    """, (f"{commit_hash}%", commit_hash))

    commit = c.fetchone()
    if not commit:
        conn.close()
        return None

    commit_dict = dict(commit)

    # Get code changes
    c.execute("""
        SELECT *
        FROM code_changes
        WHERE commit_id = ?
    """, (commit_dict['id'],))

    commit_dict['changes'] = [dict(row) for row in c.fetchall()]

    conn.close()
    return commit_dict

def search_by_file_pattern(pattern: str, limit: int = 50) -> List[Dict]:
    """Search commits that modified files matching a pattern"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT DISTINCT
            c.id as commit_id,
            c.short_hash,
            c.message,
            c.timestamp,
            r.repo_name,
            cc.file_path,
            cc.change_type,
            cc.language
        FROM git_commits c
        JOIN tracked_repos r ON c.repo_id = r.id
        JOIN code_changes cc ON c.id = cc.commit_id
        WHERE cc.file_path LIKE ? AND r.active = 1
        ORDER BY c.timestamp DESC
        LIMIT ?
    """, (f"%{pattern}%", limit))

    results = [dict(row) for row in c.fetchall()]
    conn.close()
    return results

def get_languages_used() -> List[tuple]:
    """Get all programming languages used with counts"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT language, COUNT(*) as count
        FROM code_changes
        WHERE language IS NOT NULL AND language != ''
        GROUP BY language
        ORDER BY count DESC
    """)

    results = c.fetchall()
    conn.close()
    return results

def get_recent_files(limit: int = 20) -> List[Dict]:
    """Get recently modified files across all repos"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT
            cc.file_path,
            cc.language,
            cc.change_type,
            c.timestamp,
            c.short_hash,
            c.message,
            r.repo_name
        FROM code_changes cc
        JOIN git_commits c ON cc.commit_id = c.id
        JOIN tracked_repos r ON c.repo_id = r.id
        WHERE r.active = 1
        ORDER BY c.timestamp DESC
        LIMIT ?
    """, (limit,))

    results = [dict(row) for row in c.fetchall()]
    conn.close()
    return results
