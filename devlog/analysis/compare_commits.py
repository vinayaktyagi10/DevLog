"""
Compare multiple commits to identify trends
"""
from typing import List, Dict
from collections import Counter
import sqlite3
from devlog.paths import DB_PATH


class CommitComparer:
    """Compare and analyze trends across commits"""

    def compare_commits(self, commit_hashes: List[str]) -> Dict:
        """Compare multiple commits"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Gather data
        all_languages = []
        all_file_types = []
        total_insertions = 0
        total_deletions = 0

        for commit_hash in commit_hashes:
            c.execute("""
                SELECT * FROM git_commits
                WHERE commit_hash LIKE ? OR short_hash = ?
            """, (f"{commit_hash}%", commit_hash))

            commit = c.fetchone()
            if commit:
                total_insertions += commit['insertions']
                total_deletions += commit['deletions']

                # Get file changes
                c.execute("""
                    SELECT language, file_path FROM code_changes
                    WHERE commit_id = ?
                """, (commit['id'],))

                for change in c.fetchall():
                    if change['language']:
                        all_languages.append(change['language'])

                    # File type
                    if '.' in change['file_path']:
                        ext = change['file_path'].split('.')[-1]
                        all_file_types.append(ext)

        conn.close()

        # Analyze trends
        language_freq = Counter(all_languages)
        file_type_freq = Counter(all_file_types)

        return {
            'commits_analyzed': len(commit_hashes),
            'total_insertions': total_insertions,
            'total_deletions': total_deletions,
            'net_change': total_insertions - total_deletions,
            'top_languages': language_freq.most_common(5),
            'top_file_types': file_type_freq.most_common(5),
            'avg_changes_per_commit': (total_insertions + total_deletions) / len(commit_hashes) if commit_hashes else 0
        }
