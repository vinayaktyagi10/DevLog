import click
import sqlite3
from rich import print
from rich.table import Table
from rich.console import Console
from datetime import datetime
from devlog.core.db import init_db, get_connection
from devlog.core.git_hooks import install_hook, uninstall_hook
from devlog.core.git_ops import get_repo_info
from devlog.paths import DB_PATH

@click.group()
def cli():
    """DevLog - Personal Code Review Assistant"""
    init_db()

@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
def track(repo_path):
    """Start tracking a git repository"""
    repo_info = get_repo_info(repo_path)

    if not repo_info:
        print("[bold red]Error:[/] Not a valid git repository")
        return

    if install_hook(repo_path):
        print(f"[bold green]✓[/] Now tracking: {repo_info['name']}")
        print(f"[dim]Path: {repo_info['path']}[/]")
        print(f"[dim]Branch: {repo_info['branch']}[/]")
    else:
        print("[bold red]Error:[/] Failed to install hook")

@cli.command()
@click.argument("repo_path", type=click.Path(exists=True))
def untrack(repo_path):
    """Stop tracking a git repository"""
    if uninstall_hook(repo_path):
        print(f"[bold green]✓[/] Stopped tracking repository")
    else:
        print("[bold red]Error:[/] Failed to uninstall hook")

@cli.command()
def repos():
    """List all tracked repositories"""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT repo_name, repo_path, tracked_since, last_commit_at,
               commit_count, active
        FROM tracked_repos
        ORDER BY active DESC, last_commit_at DESC
    """)

    repos = c.fetchall()
    conn.close()

    if not repos:
        print("[yellow]No repositories tracked yet[/]")
        print("Use [bold]devlog track <repo-path>[/] to start tracking")
        return

    table = Table(title="Tracked Repositories")
    table.add_column("Name", style="cyan")
    table.add_column("Path", style="dim")
    table.add_column("Commits", justify="right", style="green")
    table.add_column("Last Commit", style="magenta")
    table.add_column("Status", style="yellow")

    for repo in repos:
        name, path, tracked_since, last_commit, count, active = repo
        status = "✓ Active" if active else "○ Inactive"
        last = last_commit.split('T')[0] if last_commit else "Never"

        table.add_row(name, path, str(count), last, status)

    console = Console()
    console.print(table)

@cli.command()
@click.option("--limit", default=20, help="Number of commits to show")
def commits(limit):
    """List recent commits from all tracked repos"""
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT r.repo_name, c.short_hash, c.message, c.timestamp,
               c.files_changed, c.branch
        FROM git_commits c
        JOIN tracked_repos r ON c.repo_id = r.id
        WHERE r.active = 1
        ORDER BY c.timestamp DESC
        LIMIT ?
    """, (limit,))

    commits = c.fetchall()
    conn.close()

    if not commits:
        print("[yellow]No commits captured yet[/]")
        print("Make a commit in a tracked repo to see it here")
        return

    table = Table(title=f"Recent Commits (last {limit})")
    table.add_column("Repo", style="cyan")
    table.add_column("Hash", style="yellow")
    table.add_column("Message", style="white")
    table.add_column("Date", style="magenta")
    table.add_column("Files", justify="right", style="green")
    table.add_column("Branch", style="dim")

    for commit in commits:
        repo, hash_val, msg, timestamp, files, branch = commit
        date = timestamp.split('T')[0]
        # Truncate long messages
        msg_short = msg[:50] + "..." if len(msg) > 50 else msg

        table.add_row(repo, hash_val, msg_short, date, str(files), branch)

    console = Console()
    console.print(table)

if __name__ == "__main__":
    cli()
