import os
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from devlog.paths import DB_PATH
from devlog.core.git_ops import is_git_repo, get_repo_info, get_commit_info, get_file_diff, detect_language

# Post-commit hook template
import sys

POST_COMMIT_HOOK = f"""#!/bin/bash
# DevLog post-commit hook

# Get the python interpreter that has devlog installed
PYTHON_BIN="{sys.executable}"

# Call devlog to capture commit
"$PYTHON_BIN" -m devlog _capture-commit "$(pwd)" 2>/dev/null || true

# Don't fail the commit if devlog fails
exit 0
"""

def install_hook(repo_path: str) -> bool:
    """Install post-commit hook in repository"""
    try:
        if not is_git_repo(repo_path):
            print(f"Error: {repo_path} is not a git repository")
            return False

        hooks_dir = Path(repo_path) / '.git' / 'hooks'
        hook_path = hooks_dir / 'post-commit'

        # Backup existing hook if present
        if hook_path.exists():
            backup_path = hook_path.with_suffix('.backup')
            if not backup_path.exists():
                hook_path.rename(backup_path)
                print(f"Backed up existing hook to {backup_path}")

        # Write new hook
        hook_path.write_text(POST_COMMIT_HOOK)
        hook_path.chmod(0o755)  # Make executable

        # Add repo to database
        repo_info = get_repo_info(repo_path)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        try:
            c.execute("""
                INSERT INTO tracked_repos (repo_name, repo_path, tracked_since)
                VALUES (?, ?, ?)
            """, (repo_info['name'], repo_info['path'], datetime.now().isoformat()))
            conn.commit()
        except sqlite3.IntegrityError:
            # Already tracked
            c.execute("""
                UPDATE tracked_repos SET active = 1 WHERE repo_path = ?
            """, (repo_info['path'],))
            conn.commit()

        conn.close()
        return True

    except Exception as e:
        print(f"Error installing hook: {e}")
        return False

def uninstall_hook(repo_path: str) -> bool:
    """Remove post-commit hook from repository"""
    try:
        hook_path = Path(repo_path) / '.git' / 'hooks' / 'post-commit'

        if hook_path.exists():
            # Check if it's our hook
            content = hook_path.read_text()
            if 'DevLog post-commit hook' in content:
                hook_path.unlink()

                # Restore backup if exists
                backup_path = hook_path.with_suffix('.backup')
                if backup_path.exists():
                    backup_path.rename(hook_path)
                    print("Restored backed up hook")

        # Mark as inactive in database
        repo_path_resolved = str(Path(repo_path).resolve())
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE tracked_repos SET active = 0 WHERE repo_path = ?",
                  (repo_path_resolved,))
        conn.commit()
        conn.close()

        return True

    except Exception as e:
        print(f"Error uninstalling hook: {e}")
        return False

def capture_commit(repo_path: str):
    """Called by post-commit hook to capture commit data"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get repo ID
        repo_path_resolved = str(Path(repo_path).resolve())
        c.execute("SELECT id FROM tracked_repos WHERE repo_path = ? AND active = 1",
                  (repo_path_resolved,))
        result = c.fetchone()

        if not result:
            conn.close()
            return

        repo_id = result[0]

        # Get commit info
        commit_info = get_commit_info(repo_path)
        if not commit_info:
            conn.close()
            return

        # Insert commit
        c.execute("""
            INSERT OR IGNORE INTO git_commits
            (repo_id, commit_hash, short_hash, message, author, timestamp, branch,
             files_changed, insertions, deletions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            repo_id,
            commit_info['hash'],
            commit_info['short_hash'],
            commit_info['message'],
            commit_info['author'],
            commit_info['timestamp'],
            commit_info['branch'],
            commit_info['files_changed'],
            commit_info['insertions'],
            commit_info['deletions']
        ))

        commit_id = c.lastrowid

        # Insert code changes
        for file_info in commit_info['changed_files']:
            file_path = file_info['path']
            language = detect_language(file_path)

            # Get diff
            diff_data = get_file_diff(repo_path, commit_info['hash'], file_path)

            if diff_data:
                c.execute("""
                    INSERT INTO code_changes
                    (commit_id, file_path, change_type, language, diff_text,
                     code_before, code_after, lines_added, lines_removed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    commit_id,
                    file_path,
                    file_info['change_type'],
                    language,
                    diff_data['diff'],
                    diff_data['code_before'],
                    diff_data['code_after'],
                    diff_data['lines_added'],
                    diff_data['lines_removed']
                ))

        # Update repo stats
        c.execute("""
            UPDATE tracked_repos
            SET last_commit_at = ?, commit_count = commit_count + 1
            WHERE id = ?
        """, (commit_info['timestamp'], repo_id))

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"Error capturing commit: {e}", file=sys.stderr)
