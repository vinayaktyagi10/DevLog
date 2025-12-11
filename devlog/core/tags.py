"""
Tag management for commits
"""
import sqlite3
from datetime import datetime
from devlog.paths import DB_PATH
from typing import List, Dict


def add_tag(commit_hash: str, tag: str) -> bool:
    """Add tag to commit"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get commit ID
    c.execute("""
        SELECT id FROM git_commits
        WHERE commit_hash LIKE ? OR short_hash = ?
    """, (f"{commit_hash}%", commit_hash))

    result = c.fetchone()
    if not result:
        conn.close()
        return False

    commit_id = result[0]

    try:
        c.execute("""
            INSERT INTO commit_tags (commit_id, tag, created_at)
            VALUES (?, ?, ?)
        """, (commit_id, tag, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def remove_tag(commit_hash: str, tag: str) -> bool:
    """Remove tag from commit"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        DELETE FROM commit_tags
        WHERE commit_id = (
            SELECT id FROM git_commits
            WHERE commit_hash LIKE ? OR short_hash = ?
        ) AND tag = ?
    """, (f"{commit_hash}%", commit_hash, tag))

    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_tags(commit_hash: str) -> List[str]:
    """Get all tags for a commit"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT t.tag FROM commit_tags t
        JOIN git_commits c ON t.commit_id = c.id
        WHERE c.commit_hash LIKE ? OR c.short_hash = ?
    """, (f"{commit_hash}%", commit_hash))

    tags = [row[0] for row in c.fetchall()]
    conn.close()
    return tags


def search_by_tag(tag: str) -> List[Dict]:
    """Find commits with specific tag"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT c.*, r.repo_name
        FROM git_commits c
        JOIN tracked_repos r ON c.repo_id = r.id
        JOIN commit_tags t ON c.id = t.commit_id
        WHERE t.tag = ?
        ORDER BY c.timestamp DESC
    """, (tag,))

    results = [dict(row) for row in c.fetchall()]
    conn.close()
    return results
