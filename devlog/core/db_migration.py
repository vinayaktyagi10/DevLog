"""
Database Migration - Add FTS5 Full-Text Search Support

Run this once to enable fast full-text search in code content.
This is OPTIONAL - the system works without it, but this makes it faster.

Usage:
    python -m devlog.core.db_migration
"""

import sqlite3
from devlog.paths import DB_PATH


def add_fts5_search():
    """
    Add FTS5 virtual table for full-text search in code

    This speeds up code_search significantly
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print("Checking if FTS5 is available...")

    # Check if FTS5 is available
    try:
        c.execute("SELECT 1 FROM pragma_compile_options WHERE compile_options LIKE '%FTS5%'")
        if not c.fetchone():
            print("⚠️  FTS5 not available in your SQLite build")
            print("   The system will work fine, just slightly slower for code search")
            conn.close()
            return False
    except:
        print("⚠️  Could not detect FTS5 support")
        print("   Proceeding anyway...")

    print("Creating FTS5 table for code search...")

    try:
        # Create FTS5 virtual table
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS code_changes_fts USING fts5(
                commit_id UNINDEXED,
                file_path,
                code_after,
                diff_text,
                language UNINDEXED,
                content='code_changes',
                content_rowid='id'
            )
        """)

        print("✓ FTS5 table created")

        # Populate FTS5 table with existing data
        print("Populating FTS5 index with existing code...")
        c.execute("""
            INSERT INTO code_changes_fts(commit_id, file_path, code_after, diff_text, language)
            SELECT commit_id, file_path, code_after, diff_text, language
            FROM code_changes
            WHERE code_after IS NOT NULL OR diff_text IS NOT NULL
        """)

        rows_indexed = c.rowcount
        print(f"✓ Indexed {rows_indexed} code changes")

        # Create triggers to keep FTS5 in sync
        print("Creating triggers to keep FTS5 updated...")

        c.execute("""
            CREATE TRIGGER IF NOT EXISTS code_changes_ai AFTER INSERT ON code_changes BEGIN
                INSERT INTO code_changes_fts(commit_id, file_path, code_after, diff_text, language)
                VALUES (new.commit_id, new.file_path, new.code_after, new.diff_text, new.language);
            END
        """)

        c.execute("""
            CREATE TRIGGER IF NOT EXISTS code_changes_ad AFTER DELETE ON code_changes BEGIN
                DELETE FROM code_changes_fts WHERE rowid = old.id;
            END
        """)

        c.execute("""
            CREATE TRIGGER IF NOT EXISTS code_changes_au AFTER UPDATE ON code_changes BEGIN
                DELETE FROM code_changes_fts WHERE rowid = old.id;
                INSERT INTO code_changes_fts(commit_id, file_path, code_after, diff_text, language)
                VALUES (new.commit_id, new.file_path, new.code_after, new.diff_text, new.language);
            END
        """)

        print("✓ Triggers created")

        conn.commit()
        conn.close()

        print("\n✅ FTS5 migration complete!")
        print("   Code search will now be significantly faster")
        return True

    except sqlite3.OperationalError as e:
        print(f"❌ Error: {e}")
        print("   FTS5 might not be available. System will work without it.")
        conn.close()
        return False


def check_fts5_status():
    """Check if FTS5 is set up"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='code_changes_fts'")
        if c.fetchone():
            c.execute("SELECT COUNT(*) FROM code_changes_fts")
            count = c.fetchone()[0]
            print(f"✅ FTS5 is set up with {count} indexed code changes")
            return True
        else:
            print("ℹ️  FTS5 not set up (system will use slower LIKE search)")
            return False
    except:
        print("ℹ️  FTS5 not available")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    print("DevLog Database Migration - FTS5 Full-Text Search\n")

    if check_fts5_status():
        print("\nFTS5 already set up. Nothing to do.")
    else:
        print("\nSetting up FTS5...")
        add_fts5_search()
