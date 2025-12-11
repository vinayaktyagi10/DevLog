import click
import sqlite3
from rich import print
from rich.table import Table
from rich.console import Console
from rich.progress import Progress
from datetime import datetime
from devlog.core.db import init_db, get_connection
from devlog.core.git_hooks import install_hook, uninstall_hook
from devlog.core.git_ops import get_repo_info
from devlog.paths import DB_PATH
from devlog.core.search import (
    search_commits, get_commit_details, search_by_file_pattern,
    get_languages_used, get_recent_files
)
from devlog.core.code_extract import extract_changed_functions, get_code_summary
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import TerminalFormatter
import json
from devlog.core.embeddings import semantic_search, embed_all_commits

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

@cli.command('_capture-commit')
@click.argument("repo_path")
def _capture_commit(repo_path):
    """Internal: Called by git hook to capture commit"""
    from devlog.core.git_hooks import capture_commit
    try:
        capture_commit(repo_path)
    except Exception as e:
        pass

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

@cli.command()
@click.argument("query")
@click.option("--repo", help="Filter by repository name")
@click.option("--lang", help="Filter by language (python, javascript, etc)")
@click.option("--after", help="After date (YYYY-MM-DD)")
@click.option("--before", help="Before date (YYYY-MM-DD)")
@click.option("--limit", default=20, help="Maximum results")
def find(query, repo, lang, after, before, limit):
    """Search commits by keyword, file, or content"""
    results = search_commits(
        query=query,
        repo_name=repo,
        language=lang,
        after_date=after,
        before_date=before,
        limit=limit
    )

    if not results:
        print(f"[yellow]No commits found matching '{query}'[/]")
        return

    print(f"\n[bold green]Found {len(results)} commits matching '{query}'[/]\n")

    for result in results:
        print(f"[cyan]{result['repo_name']}[/] [yellow]{result['short_hash']}[/] [dim]{result['timestamp'].split('T')[0]}[/]")
        print(f"  {result['message']}")

        # Show changed files
        if result['files']:
            files_str = ", ".join([f"{f['file_path']} ({f['language']})" for f in result['files'][:3]])
            if len(result['files']) > 3:
                files_str += f" and {len(result['files']) - 3} more"
            print(f"  [dim]Files: {files_str}[/]")
        print()

@cli.command()
@click.argument("commit_hash")
@click.option("--show-diff", is_flag=True, help="Show full diff")
@click.option("--show-functions", is_flag=True, help="Show changed functions only")
def show(commit_hash, show_diff, show_functions):
    """Show detailed information about a commit"""
    details = get_commit_details(commit_hash)

    if not details:
        print(f"[bold red]Commit not found:[/] {commit_hash}")
        return

    # Header
    print(f"\n[bold cyan]Commit {details['short_hash']}[/] in [yellow]{details['repo_name']}[/]")
    print(f"[dim]{details['timestamp']}[/] by {details['author']}")
    print(f"[dim]Branch: {details['branch']}[/]")
    print(f"\n[white]{details['message']}[/]\n")

    # Stats
    print(f"[green]+{details['insertions']}[/] [red]-{details['deletions']}[/] across {details['files_changed']} files")
    print()

    # Changed files
    for change in details['changes']:
        print(f"[cyan]{change['change_type']:8}[/] {change['file_path']} [dim]({change['language']})[/]")
        print(f"         [green]+{change['lines_added']}[/] [red]-{change['lines_removed']}[/]")

        if show_functions and change['code_after']:
            # Extract and show changed functions
            funcs = extract_changed_functions(
                change['diff_text'],
                change['code_after'],
                change['language']
            )

            if funcs:
                print(f"         [yellow]Changed functions:[/]")
                for func in funcs:
                    print(f"           - {func['name']} (lines {func['start_line']}-{func['end_line']})")

        if show_diff and change['diff_text']:
            print("\n[dim]" + "─" * 60 + "[/]")
            # Syntax highlight the diff
            try:
                lexer = get_lexer_by_name('diff')
                formatted = highlight(change['diff_text'], lexer, TerminalFormatter())
                print(formatted)
            except:
                print(change['diff_text'])
            print("[dim]" + "─" * 60 + "[/]\n")

        print()

@cli.command()
@click.argument("pattern")
@click.option("--limit", default=20, help="Maximum results")
def files(pattern, limit):
    """Search for commits that modified files matching a pattern"""
    results = search_by_file_pattern(pattern, limit)

    if not results:
        print(f"[yellow]No files found matching '{pattern}'[/]")
        return

    print(f"\n[bold green]Found {len(results)} commits modifying files like '{pattern}'[/]\n")

    table = Table()
    table.add_column("Repo", style="cyan")
    table.add_column("Commit", style="yellow")
    table.add_column("File", style="white")
    table.add_column("Change", style="magenta")
    table.add_column("Date", style="dim")

    for result in results:
        table.add_row(
            result['repo_name'],
            result['short_hash'],
            result['file_path'],
            result['change_type'],
            result['timestamp'].split('T')[0]
        )

    console = Console()
    console.print(table)

@cli.command()
def stats():
    """Show statistics about your coding activity"""
    conn = get_connection()
    c = conn.cursor()

    # Total commits
    c.execute("SELECT COUNT(*) FROM git_commits")
    total_commits = c.fetchone()[0]

    # Total lines changed
    c.execute("SELECT SUM(insertions), SUM(deletions) FROM git_commits")
    insertions, deletions = c.fetchone()

    # Commits by repo
    c.execute("""
        SELECT r.repo_name, COUNT(*) as count
        FROM git_commits c
        JOIN tracked_repos r ON c.repo_id = r.id
        WHERE r.active = 1
        GROUP BY r.repo_name
        ORDER BY count DESC
    """)
    repos = c.fetchall()

    # Languages
    languages = get_languages_used()

    # Recent activity (commits per day, last 30 days)
    c.execute("""
        SELECT DATE(timestamp) as date, COUNT(*) as count
        FROM git_commits
        WHERE timestamp >= DATE('now', '-30 days')
        GROUP BY date
        ORDER BY date DESC
        LIMIT 10
    """)
    recent = c.fetchall()

    conn.close()

    # Display
    print("\n[bold cyan] Coding Statistics[/]\n")

    print(f"[green]Total Commits:[/] {total_commits}")
    print(f"[green]Lines Added:[/] {insertions or 0}")
    print(f"[red]Lines Deleted:[/] {deletions or 0}")
    print(f"[yellow]Net Change:[/] {(insertions or 0) - (deletions or 0):+}")

    print("\n[bold]Commits by Repository:[/]")
    for repo, count in repos:
        print(f"  {repo}: {count}")

    print("\n[bold]Languages Used:[/]")
    for lang, count in languages[:10]:
        print(f"  {lang}: {count} files")

    if recent:
        print("\n[bold]Recent Activity (last 10 days):[/]")
        for date, count in recent:
            bar = "█" * min(count, 20)
            print(f"  {date}: {bar} {count}")

    print()

@cli.command()
@click.option("--limit", default=20, help="Number of files to show")
def recent(limit):
    """Show recently modified files"""
    files = get_recent_files(limit)

    if not files:
        print("[yellow]No recent files found[/]")
        return

    table = Table(title=f"Recently Modified Files (last {limit})")
    table.add_column("File", style="white")
    table.add_column("Repo", style="cyan")
    table.add_column("Language", style="yellow")
    table.add_column("Change", style="magenta")
    table.add_column("Date", style="dim")
    table.add_column("Commit", style="green")

    for f in files:
        table.add_row(
            f['file_path'],
            f['repo_name'],
            f['language'] or '?',
            f['change_type'],
            f['timestamp'].split('T')[0],
            f['short_hash']
        )

    console = Console()
    console.print(table)

@cli.command()
@click.argument("query")
@click.option("--limit", default=10, help="Maximum results")
def semantic(query, limit):
    """Search commits using semantic similarity (understands meaning)"""
    results = semantic_search(query, limit)

    if not results:
        print(f"[yellow]No results found. Run 'devlog embed' first to generate embeddings.[/]")
        return

    print(f"\n[bold green]Semantic search results for: '{query}'[/]\n")

    for result in results:
        similarity_pct = result['similarity'] * 100
        print(f"[cyan]{result['repo_name']}[/] [yellow]{result['short_hash']}[/] [dim]({similarity_pct:.1f}% match)[/]")
        print(f"  {result['message']}")
        print(f"  [dim]{result['timestamp'].split('T')[0]}[/]\n")

@cli.command()
def embed():
    """Generate semantic embeddings for all commits (enables semantic search)"""
    embed_all_commits()

@cli.command()
@click.argument("commit_hash")
@click.option("--type", "analysis_type", default="quick",
              type=click.Choice(['quick', 'deep', 'patterns']),
              help="Analysis type")
@click.option("--no-cache", is_flag=True, help="Force new analysis, ignore cache")
def analyze(commit_hash, analysis_type, no_cache):
    """Analyze a specific commit with AI"""
    from devlog.analysis.analyzer import CodeAnalyzer
    from devlog.analysis.llm import test_connection

    # Check if Ollama is running
    if not test_connection():
        print("[bold red]Error:[/] Cannot connect to Ollama")
        print("[yellow]Make sure Ollama is running:[/] ollama serve")
        return

    analyzer = CodeAnalyzer()

    # Clear cache if requested
    if no_cache:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            DELETE FROM analyses
            WHERE commit_id = (
                SELECT id FROM git_commits
                WHERE commit_hash LIKE ? OR short_hash = ?
            )
        """, (f"{commit_hash}%", commit_hash))
        conn.commit()
        conn.close()

    print(f"[yellow]Analyzing commit {commit_hash}...[/]")

    result = analyzer.analyze_commit(commit_hash, analysis_type)

    if not result:
        print(f"[bold red]Commit not found:[/] {commit_hash}")
        return

    # Display results
    print(f"\n[bold cyan]Analysis Results[/] [dim]({analysis_type})[/]")
    print(f"[dim]Commit: {result['commit_hash']} in {result['repo_name']}[/]")

    if result.get('cached'):
        print("[dim]Using cached analysis[/]")

    print(f"\n[bold]Summary:[/]")
    print(result['summary'])

    if result.get('issues'):
        print(f"\n[bold red]Issues Found ({len(result['issues'])}):[/]")
        for i, issue in enumerate(result['issues'][:10], 1):
            print(f"  {i}. {issue}")
        if len(result['issues']) > 10:
            print(f"  [dim]...and {len(result['issues']) - 10} more[/]")

    if result.get('suggestions'):
        print(f"\n[bold green]Suggestions ({len(result['suggestions'])}):[/]")
        for i, suggestion in enumerate(result['suggestions'][:10], 1):
            print(f"  {i}. {suggestion}")
        if len(result['suggestions']) > 10:
            print(f"  [dim]...and {len(result['suggestions']) - 10} more[/]")

    if analysis_type == 'deep' and result.get('quality_score'):
        score = result['quality_score']
        color = "green" if score >= 70 else "yellow" if score >= 50 else "red"
        print(f"\n[bold]Code Quality Score:[/] [{color}]{score}/100[/]")

        if result.get('patterns'):
            print(f"\n[bold cyan]Patterns Found:[/]")
            for pattern in result['patterns'][:5]:
                print(f"  • {pattern}")

        if result.get('anti_patterns'):
            print(f"\n[bold red]Anti-Patterns:[/]")
            for anti in result['anti_patterns'][:5]:
                print(f"  • {anti}")

    if analysis_type == 'patterns' and result.get('patterns'):
        patterns_dict = result['patterns']
        for category, items in patterns_dict.items():
            if items:
                print(f"\n[bold]{category.replace('_', ' ').title()}:[/]")
                for item in items[:5]:
                    print(f"  • {item}")

    print()


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
def analyze_file(file_path):
    """Analyze current state of a file"""
    from devlog.analysis.analyzer import CodeAnalyzer
    from devlog.analysis.llm import test_connection
    from devlog.core.git_ops import detect_language

    if not test_connection():
        print("[bold red]Error:[/] Cannot connect to Ollama")
        return

    # Read file
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
    except Exception as e:
        print(f"[bold red]Error reading file:[/] {e}")
        return

    language = detect_language(file_path)

    print(f"[yellow]Analyzing {file_path}...[/]")

    analyzer = CodeAnalyzer()
    result = analyzer.analyze_file(file_path, code, language)

    # Display results
    print(f"\n[bold cyan]File Analysis[/]")
    print(f"[dim]Language: {language}[/]")

    if result.get('issues'):
        print(f"\n[bold red]Issues ({len(result['issues'])}):[/]")
        for i, issue in enumerate(result['issues'], 1):
            print(f"  {i}. {issue}")

    if result.get('suggestions'):
        print(f"\n[bold green]Suggestions ({len(result['suggestions'])}):[/]")
        for i, suggestion in enumerate(result['suggestions'], 1):
            print(f"  {i}. {suggestion}")

    print()


@cli.command()
@click.option("--repo", help="Repository name to analyze")
@click.option("--limit", default=10, help="Number of commits to analyze")
def batch_analyze(repo, limit):
    """Analyze multiple commits in a repository"""
    from devlog.analysis.analyzer import CodeAnalyzer
    from devlog.analysis.llm import test_connection
    from rich.progress import Progress

    if not test_connection():
        print("[bold red]Error:[/] Cannot connect to Ollama")
        return

    if not repo:
        # Get first active repo
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT repo_name FROM tracked_repos WHERE active = 1 LIMIT 1")
        result = c.fetchone()
        conn.close()

        if not result:
            print("[bold red]No tracked repositories found[/]")
            return

        repo = result[0]

    print(f"[yellow]Analyzing last {limit} commits in {repo}...[/]")

    analyzer = CodeAnalyzer()

    with Progress() as progress:
        task = progress.add_task("[cyan]Analyzing...", total=limit)

        results = analyzer.batch_analyze(repo, limit)

        for result in results:
            progress.update(task, advance=1)

    # Summary
    total_issues = sum(len(r.get('issues', [])) for r in results)
    total_suggestions = sum(len(r.get('suggestions', [])) for r in results)

    print(f"\n[bold green]Batch Analysis Complete[/]")
    print(f"Analyzed {len(results)} commits")
    print(f"Found {total_issues} total issues")
    print(f"Generated {total_suggestions} suggestions")

    # Show top issues
    all_issues = []
    for r in results:
        for issue in r.get('issues', []):
            all_issues.append((r['commit_hash'], issue))

    if all_issues:
        print(f"\n[bold red]Top Issues:[/]")
        for i, (commit, issue) in enumerate(all_issues[:5], 1):
            print(f"  {i}. [{commit}] {issue}")

    print()


@cli.command()
def analyses():
    """List all cached analyses"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT
            a.id,
            c.short_hash,
            r.repo_name,
            a.analysis_type,
            a.analyzed_at,
            a.summary
        FROM analyses a
        JOIN git_commits c ON a.commit_id = c.id
        JOIN tracked_repos r ON c.repo_id = r.id
        ORDER BY a.analyzed_at DESC
        LIMIT 20
    """)

    results = c.fetchall()
    conn.close()

    if not results:
        print("[yellow]No analyses found[/]")
        print("Run [bold]devlog analyze <commit-hash>[/] to analyze commits")
        return

    table = Table(title="Recent Analyses")
    table.add_column("ID", style="dim")
    table.add_column("Commit", style="yellow")
    table.add_column("Repo", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Date", style="dim")
    table.add_column("Summary", style="white")

    for row in results:
        table.add_row(
            str(row['id']),
            row['short_hash'],
            row['repo_name'],
            row['analysis_type'],
            row['analyzed_at'].split('T')[0],
            row['summary'][:60] + "..." if len(row['summary']) > 60 else row['summary']
        )

    console = Console()
    console.print(table)


@cli.command()
@click.argument("analysis_id", type=int)
def show_analysis(analysis_id):
    """Show details of a cached analysis"""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT
            a.*,
            c.short_hash,
            c.message,
            r.repo_name
        FROM analyses a
        JOIN git_commits c ON a.commit_id = c.id
        JOIN tracked_repos r ON c.repo_id = r.id
        WHERE a.id = ?
    """, (analysis_id,))

    result = c.fetchone()
    conn.close()

    if not result:
        print(f"[bold red]Analysis not found:[/] {analysis_id}")
        return

    print(f"\n[bold cyan]Analysis #{analysis_id}[/]")
    print(f"[dim]Commit: {result['short_hash']} in {result['repo_name']}[/]")
    print(f"[dim]Type: {result['analysis_type']}[/]")
    print(f"[dim]Date: {result['analyzed_at'].split('T')[0]}[/]")
    print(f"\n[bold]Commit Message:[/]")
    print(result['message'])

    print(f"\n[bold]Summary:[/]")
    print(result['summary'])

    if result['issues']:
        issues = json.loads(result['issues'])
        print(f"\n[bold red]Issues ({len(issues)}):[/]")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")

    if result['suggestions']:
        suggestions = json.loads(result['suggestions'])
        print(f"\n[bold green]Suggestions ({len(suggestions)}):[/]")
        for i, suggestion in enumerate(suggestions, 1):
            print(f"  {i}. {suggestion}")

    if result['patterns']:
        patterns = json.loads(result['patterns'])
        if isinstance(patterns, dict):
            for category, items in patterns.items():
                if items:
                    print(f"\n[bold]{category.replace('_', ' ').title()}:[/]")
                    for item in items:
                        print(f"  • {item}")
        elif isinstance(patterns, list) and patterns:
            print(f"\n[bold]Patterns:[/]")
            for item in patterns:
                print(f"  • {item}")

    print()


# Also add this test command
@cli.command()
def test_llm():
    """Test connection to Ollama"""
    from devlog.analysis.llm import test_connection, LLMConfig

    print(f"[yellow]Testing connection to Ollama...[/]")
    print(f"[dim]URL: {LLMConfig.BASE_URL}[/]")
    print(f"[dim]Model: {LLMConfig.MODEL}[/]")

    if test_connection():
        print("[bold green]✓ Connection successful![/]")
        print("You can now use analysis commands")
    else:
        print("[bold red]✗ Connection failed[/]")
        print("\n[yellow]Troubleshooting:[/]")
        print("1. Make sure Ollama is installed")
        print("2. Start Ollama: [bold]ollama serve[/]")
        print("3. Pull the model: [bold]ollama pull 'model name' [/]")

if __name__ == "__main__":
    cli()
