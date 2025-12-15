import sqlite3
import os
from devlog.paths import DB_PATH, DB_DIR
from datetime import datetime

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS tracked_repos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_name TEXT NOT NULL,
            repo_path TEXT NOT NULL UNIQUE,
            tracked_since TEXT NOT NULL,
            last_commit_at TEXT,
            commit_count INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT 1
        );
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS git_commits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_id INTEGER NOT NULL,
            commit_hash TEXT NOT NULL,
            short_hash TEXT NOT NULL,
            message TEXT NOT NULL,
            author TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            branch TEXT,
            files_changed INTEGER DEFAULT 0,
            insertions INTEGER DEFAULT 0,
            deletions INTEGER DEFAULT 0,
            FOREIGN KEY(repo_id) REFERENCES tracked_repos(id),
            UNIQUE(repo_id, commit_hash)
        );
    """)

    # Code changes (diffs)
    c.execute("""
        CREATE TABLE IF NOT EXISTS code_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            change_type TEXT NOT NULL,
            language TEXT,
            diff_text TEXT,
            code_before TEXT,
            code_after TEXT,
            lines_added INTEGER DEFAULT 0,
            lines_removed INTEGER DEFAULT 0,
            FOREIGN KEY(commit_id) REFERENCES git_commits(id)
        );
    """)

    # AI analysis cache
    c.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_id INTEGER NOT NULL,
            analysis_type TEXT NOT NULL,
            summary TEXT,
            issues TEXT,
            suggestions TEXT,
            patterns TEXT,
            analyzed_at TEXT NOT NULL,
            FOREIGN KEY(commit_id) REFERENCES git_commits(id)
        );
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            commits_analyzed TEXT,
            your_code TEXT,
            web_sources TEXT,
            comparison TEXT,
            recommendations TEXT,
            created_at TEXT NOT NULL
        );
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS commit_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(commit_id) REFERENCES git_commits(id),
            UNIQUE(commit_id, tag)
        );
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_commits_repo ON git_commits(repo_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_commits_timestamp ON git_commits(timestamp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_changes_commit ON code_changes(commit_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_changes_language ON code_changes(language)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tags_commit ON commit_tags(commit_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tags_tag ON commit_tags(tag)")

    conn.commit()
    conn.close()

def get_connection():
    """Get database connection"""
    return sqlite3.connect(DB_PATH)
