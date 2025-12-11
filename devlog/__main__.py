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
from devlog.search.web_search import WebSearcher
from devlog.search.scraper import WebScraper
from devlog.search.content_extractor import ContentExtractor
from devlog.analysis.review import ReviewPipeline

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

@cli.command()
@click.argument("query")
@click.option("--limit", default=10, help="Number of results")
def search_web(query, limit):
    """Search web for technical information"""
    from devlog.search.web_search import WebSearcher

    searcher = WebSearcher()
    print(f"[yellow]Searching for: {query}[/]")
    print(f"[dim]Using: {'Brave API' if searcher.use_brave else 'DuckDuckGo'}[/]\n")

    results = searcher.search(query, num_results=limit)

    if not results:
        print("[red]No results found[/]")
        return

    table = Table(title=f"Search Results ({len(results)})")
    table.add_column("#", style="dim", width=3)
    table.add_column("Title", style="cyan")
    table.add_column("Source", style="yellow", width=25)
    table.add_column("Score", justify="right", style="green", width=6)

    for i, result in enumerate(results, 1):
        table.add_row(
            str(i),
            result['title'][:60] + "..." if len(result['title']) > 60 else result['title'],
            result['source'],
            f"{result['score']:.2f}"
        )

    console = Console()
    console.print(table)

    # Show top result details
    print(f"\n[bold]Top Result:[/]")
    top = results[0]
    print(f"[cyan]{top['title']}[/]")
    print(f"[dim]{top['url']}[/]")
    print(f"{top['snippet'][:200]}...")


@cli.command()
@click.argument("topic")
@click.option("--language", help="Programming language")
def best_practices(topic, language):
    """Search and summarize best practices for a topic"""
    from devlog.search.web_search import WebSearcher
    from devlog.search.scraper import WebScraper
    from devlog.search.content_extractor import ContentExtractor

    print(f"[yellow]Finding best practices for: {topic}[/]")
    if language:
        print(f"[dim]Language: {language}[/]")

    # Search
    searcher = WebSearcher()
    results = searcher.search_topic(topic, language, num_results=5)

    if not results:
        print("[red]No results found[/]")
        return

    print(f"[green]✓[/] Found {len(results)} sources")

    # Scrape top 3
    print("[yellow]Scraping sources...[/]")
    scraper = WebScraper()
    contents = scraper.scrape_multiple([r['url'] for r in results[:3]])

    print(f"[green]✓[/] Scraped {len(contents)} sources")

    # Extract practices
    print("[yellow]Extracting best practices...[/]")
    extractor = ContentExtractor()

    all_practices = []
    all_examples = []

    for content in contents:
        practices = extractor.extract_best_practices(content)
        examples = extractor.extract_code_examples(content)

        all_practices.extend(practices)
        all_examples.extend(examples)

    print(f"[green]✓[/] Found {len(all_practices)} practices, {len(all_examples)} code examples\n")

    # Display
    print(f"[bold cyan]Best Practices for {topic}:[/]\n")

    for i, practice in enumerate(all_practices[:10], 1):
        print(f"{i}. {practice}")

    if all_examples:
        print(f"\n[bold cyan]Code Examples:[/]\n")
        for i, example in enumerate(all_examples[:3], 1):
            print(f"[bold]Example {i}:[/] [dim]({example['language']})[/]")
            code_lines = example['code'].split('\n')[:10]
            for line in code_lines:
                print(f"  {line}")
            if len(example['code'].split('\n')) > 10:
                print("  ...")
            print()


@cli.command()
@click.argument("topic")
@click.option("--language", help="Filter by programming language")
@click.option("--commits", default=5, help="Number of commits to analyze")
@click.option("--deep", is_flag=True, help="Use deep analysis")
def review(topic, language, commits, deep):
    """Full code review: your code + web best practices + comparison"""
    from devlog.analysis.review import ReviewPipeline
    from devlog.analysis.llm import test_connection

    # Check Ollama
    if not test_connection():
        print("[bold red]Error:[/] Cannot connect to Ollama")
        print("[yellow]Start Ollama:[/] ollama serve")
        return

    print(f"\n[bold cyan]Starting Full Code Review[/]")
    print(f"[dim]Topic: {topic}[/]")
    if language:
        print(f"[dim]Language: {language}[/]")
    print()

    pipeline = ReviewPipeline()

    try:
        review_result = pipeline.review_topic(topic, language, commits, deep)

        if 'error' in review_result:
            print(f"[bold red]Error:[/] {review_result['error']}")
            if 'suggestion' in review_result:
                print(f"[yellow]Suggestion:[/] {review_result['suggestion']}")
            return

        # Generate and display report
        print("\n" + "=" * 70)
        print(pipeline.generate_report(review_result, format='text'))
        print("=" * 70)

        print(f"\n[green]✓ Review complete![/]")
        print(f"[dim]Review ID: {review_result.get('id')}[/]")
        print(f"[dim]View again: devlog show-review {review_result.get('id')}[/]")

    except Exception as e:
        print(f"[bold red]Review failed:[/] {e}")
        import traceback
        traceback.print_exc()


@cli.command()
@click.option("--limit", default=20, help="Number of reviews to show")
def reviews(limit):
    """List all code reviews"""
    from devlog.analysis.review import ReviewPipeline

    pipeline = ReviewPipeline()
    review_list = pipeline.list_reviews(limit)

    if not review_list:
        print("[yellow]No reviews found yet[/]")
        print("Run [bold]devlog review <topic>[/] to create one")
        return

    table = Table(title="Code Reviews")
    table.add_column("ID", style="dim", width=5)
    table.add_column("Topic", style="cyan")
    table.add_column("Commits", justify="right", style="green", width=8)
    table.add_column("Date", style="magenta")

    for review in review_list:
        # Parse commits_analyzed JSON
        try:
            commits = json.loads(review['commits_analyzed'])
            num_commits = len(commits) if isinstance(commits, list) else 0
        except:
            num_commits = 0

        table.add_row(
            str(review['id']),
            review['topic'],
            str(num_commits),
            review['created_at'].split('T')[0]
        )

    console = Console()
    console.print(table)


@cli.command()
@click.argument("review_id", type=int)
@click.option("--format", type=click.Choice(['text', 'markdown']), default='text')
@click.option("--save", help="Save report to file")
def show_review(review_id, format, save):
    """Show detailed review report"""
    from devlog.analysis.review import ReviewPipeline

    pipeline = ReviewPipeline()
    review = pipeline.get_review(review_id)

    if not review:
        print(f"[bold red]Review not found:[/] {review_id}")
        return

    # Parse JSON fields
    try:
        review['comparison'] = json.loads(review.get('comparison', '{}'))
        review['your_analysis'] = json.loads(review.get('your_analysis', '{}'))
    except:
        pass

    # Generate report
    report = pipeline.generate_report(review, format=format)

    # Display or save
    if save:
        with open(save, 'w') as f:
            f.write(report)
        print(f"[green]✓[/] Report saved to: {save}")
    else:
        print(report)


@cli.command()
@click.argument("url")
def scrape(url):
    """Scrape and display content from a URL (for testing)"""
    from devlog.search.scraper import WebScraper

    print(f"[yellow]Scraping:[/] {url}")

    scraper = WebScraper()
    content = scraper.scrape_url(url)

    if not content:
        print("[red]Failed to scrape URL[/]")
        return

    print(f"\n[bold cyan]Title:[/] {content.get('title', 'N/A')}")
    print(f"[bold]Source Type:[/] {content.get('source_type', 'unknown')}")
    print(f"[bold]Quality Score:[/] {scraper.score_content_quality(content):.2f}")

    if content.get('votes'):
        print(f"[bold]Votes:[/] {content['votes']}")

    print(f"\n[bold cyan]Content Preview:[/]")
    print(content.get('content', '')[:500] + "...")

    if content.get('code_blocks'):
        print(f"\n[bold cyan]Code Blocks Found:[/] {len(content['code_blocks'])}")
        if content['code_blocks']:
            print("\n[bold]First Code Block:[/]")
            print(content['code_blocks'][0][:300])
            if len(content['code_blocks'][0]) > 300:
                print("...")

@cli.command()
@click.argument("review_id", type=int)
@click.option("--format", type=click.Choice(['markdown', 'json']), default='markdown')
@click.option("--output", help="Output file path")
def export_review(review_id, format, output):
    """Export review to file"""
    from devlog.analysis.review import ReviewPipeline
    from devlog.export.report_generator import ReportGenerator

    pipeline = ReviewPipeline()
    review = pipeline.get_review(review_id)

    if not review:
        print(f"[bold red]Review not found:[/] {review_id}")
        return

    # Generate filename if not provided
    if not output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = 'md' if format == 'markdown' else 'json'
        output = f"review_{review_id}_{timestamp}.{ext}"

    generator = ReportGenerator()
    generator.save_report(review, output, format)

    print(f"[green]✓[/] Report saved to: {output}")

@cli.command()
@click.argument("commit_hashes", nargs=-1)
def compare(commit_hashes):
    """Compare multiple commits to identify trends"""
    from devlog.analysis.compare_commits import CommitComparer

    if len(commit_hashes) < 2:
        print("[red]Please provide at least 2 commit hashes[/]")
        return

    comparer = CommitComparer()
    result = comparer.compare_commits(list(commit_hashes))

    print(f"\n[bold cyan]Comparing {result['commits_analyzed']} Commits[/]\n")
    print(f"[green]Total additions:[/] {result['total_insertions']}")
    print(f"[red]Total deletions:[/] {result['total_deletions']}")
    print(f"[yellow]Net change:[/] {result['net_change']:+}")
    print(f"[dim]Avg changes/commit:[/] {result['avg_changes_per_commit']:.1f}")

    if result['top_languages']:
        print(f"\n[bold]Top Languages:[/]")
        for lang, count in result['top_languages']:
            print(f"  {lang}: {count} files")

    print()

@cli.command()
def tui():
    """Launch interactive TUI (Terminal User Interface)"""
    from devlog.cli.tui import run_tui

    print("[cyan]Launching DevLog TUI...[/]")
    print("[dim]Press ? for help, q to quit[/]\n")

    try:
        run_tui()
    except KeyboardInterrupt:
        print("\n[yellow]TUI closed[/]")
    except Exception as e:
        print(f"[red]TUI error:[/] {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    cli()
