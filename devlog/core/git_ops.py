import git
import os
from pathlib import Path
from typing import Optional, Dict, List, Tuple

def is_git_repo(path: str) -> bool:
    """Check if a path is a git repository"""
    try:
        git.Repo(path)
        return True
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return False

def get_repo_info(path: str) -> Optional[Dict]:
    """Get information about a git repository"""
    try:
        repo = git.Repo(path)
        return {
            'name': Path(path).resolve().name,
            'path': str(Path(path).resolve()),
            'branch': repo.active_branch.name,
            'remote': repo.remotes[0].url if repo.remotes else None,
            'is_dirty': repo.is_dirty(),
        }
    except Exception as e:
        print(f"Error getting repo info: {e}")
        return None

def get_commit_info(repo_path: str, commit_hash: str = 'HEAD') -> Optional[Dict]:
    """Get detailed commit information"""
    try:
        repo = git.Repo(repo_path)
        commit = repo.commit(commit_hash)

        # Get diff stats
        stats = commit.stats.total

        # Get changed files
        changed_files = []
        if commit.parents:
            parent = commit.parents[0]
            diffs = parent.diff(commit)

            for diff in diffs:
                change_type = 'modified'
                if diff.new_file:
                    change_type = 'added'
                elif diff.deleted_file:
                    change_type = 'deleted'
                elif diff.renamed_file:
                    change_type = 'renamed'

                changed_files.append({
                    'path': diff.b_path or diff.a_path,
                    'change_type': change_type,
                    'a_path': diff.a_path,
                    'b_path': diff.b_path
                })

        return {
            'hash': commit.hexsha,
            'short_hash': commit.hexsha[:7],
            'message': commit.message.strip(),
            'author': str(commit.author),
            'timestamp': commit.committed_datetime.isoformat(),
            'branch': repo.active_branch.name,
            'files_changed': stats['files'],
            'insertions': stats['insertions'],
            'deletions': stats['deletions'],
            'changed_files': changed_files
        }
    except Exception as e:
        print(f"Error getting commit info: {e}")
        return None

def get_file_diff(repo_path: str, commit_hash: str, file_path: str) -> Optional[Dict]:
    """Get diff for a specific file in a commit"""
    try:
        repo = git.Repo(repo_path)
        commit = repo.commit(commit_hash)

        if not commit.parents:
            # Initial commit - show entire file
            try:
                content = (commit.tree / file_path).data_stream.read().decode('utf-8')
                return {
                    'diff': content,
                    'code_before': '',
                    'code_after': content,
                    'lines_added': len(content.splitlines()),
                    'lines_removed': 0
                }
            except:
                return None

        parent = commit.parents[0]
        diffs = parent.diff(commit, paths=file_path, create_patch=True)

        if not diffs:
            return None

        diff_obj = diffs[0]

        # Get before/after content
        code_before = ''
        code_after = ''

        try:
            if diff_obj.a_blob:
                code_before = diff_obj.a_blob.data_stream.read().decode('utf-8', errors='ignore')
        except:
            pass

        try:
            if diff_obj.b_blob:
                code_after = diff_obj.b_blob.data_stream.read().decode('utf-8', errors='ignore')
        except:
            pass

        # Parse diff to count lines
        diff_text = diff_obj.diff.decode('utf-8', errors='ignore')
        lines_added = diff_text.count('\n+')
        lines_removed = diff_text.count('\n-')

        return {
            'diff': diff_text,
            'code_before': code_before,
            'code_after': code_after,
            'lines_added': lines_added,
            'lines_removed': lines_removed
        }
    except Exception as e:
        print(f"Error getting file diff: {e}")
        return None

def detect_language(file_path: str) -> str:
    """Detect programming language from file extension"""
    ext_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'javascript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.cpp': 'cpp',
        '.c': 'c',
        '.h': 'c',
        '.hpp': 'cpp',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.php': 'php',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.scala': 'scala',
        '.sql': 'sql',
        '.sh': 'bash',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.json': 'json',
        '.xml': 'xml',
        '.html': 'html',
        '.css': 'css',
        '.scss': 'scss',
        '.md': 'markdown',
    }

    ext = Path(file_path).suffix.lower()
    return ext_map.get(ext, 'text')
