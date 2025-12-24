"""
DevLog Enhanced TUI - Beautiful, Functional Terminal Interface
Complete code review assistant with web search, AI analysis, and review workflow
"""
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll, ScrollableContainer
from textual.widgets import (
    Header, Footer, Static, ListView, ListItem, Label,
    Input, Button, TabbedContent, TabPane, DataTable, Tree, ProgressBar
)
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from textual import work
from rich.syntax import Syntax
from rich.panel import Panel
from rich.text import Text
from rich.table import Table as RichTable
from rich.progress import Progress as RichProgress
import sqlite3
from datetime import datetime
from devlog.paths import DB_PATH
from devlog.core.search import get_commit_details, search_commits
from devlog.analysis.analyzer import CodeAnalyzer
from devlog.analysis.llm import test_connection
from devlog.search.web_search import WebSearcher
from devlog.analysis.review import ReviewPipeline
import asyncio
import webbrowser


import logging

# Setup debug logging
logging.basicConfig(
    filename='devlog_tui_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== MODAL SCREENS ====================

class ReviewInputModal(ModalScreen):
    """Modal for review topic input"""

    CSS = """
    ReviewInputModal {
        align: center middle;
    }

    #dialog {
        width: 60;
        height: 15;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #dialog Input {
        margin: 1 0;
    }

    #dialog Horizontal {
        height: 3;
        align: center middle;
    }

    #dialog Button {
        margin: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_mount(self) -> None:
        self.query_one("#topic-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in inputs"""
        self.submit_form()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-btn":
            self.submit_form()
        else:
            self.dismiss(None)

    def submit_form(self) -> None:
        topic = self.query_one("#topic-input", Input).value
        language = self.query_one("#language-input", Input).value or None
        try:
            commits = int(self.query_one("#commits-input", Input).value)
        except:
            commits = 5

        if topic:
            self.dismiss((topic, language, commits))
        else:
            self.app.notify("Please enter a topic", severity="warning")

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("[bold cyan]Start Code Review[/]")
            yield Label("Topic (e.g., 'authentication', 'error handling'):")
            yield Input(placeholder="Enter topic...", id="topic-input")
            yield Label("Language (optional):")
            yield Input(placeholder="e.g., python", id="language-input")
            yield Label("Number of commits:")
            yield Input(value="5", id="commits-input")
            with Horizontal():
                yield Button("Start Review", variant="primary", id="start-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")


class WebSearchModal(ModalScreen):
    """Modal for web search input"""

    CSS = """
    WebSearchModal {
        align: center middle;
    }

    #dialog {
        width: 60;
        height: 11;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #dialog Input {
        margin: 1 0;
    }

    #dialog Horizontal {
        height: 3;
        align: center middle;
    }

    #dialog Button {
        margin: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_mount(self) -> None:
        self.query_one("#query-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key"""
        self.submit_search()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "search-btn":
            self.submit_search()
        else:
            self.dismiss(None)

    def submit_search(self) -> None:
        query = self.query_one("#query-input", Input).value
        if query:
            self.dismiss(query)
        else:
            self.app.notify("Please enter a search query", severity="warning")

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("[bold cyan]Web Search[/]")
            yield Label("Search query:")
            yield Input(placeholder="e.g., 'python JWT best practices'", id="query-input")
            with Horizontal():
                yield Button("Search", variant="primary", id="search-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")


# ==================== CUSTOM WIDGETS ====================

class StatsPanel(Static):
    """Dashboard statistics panel"""

    def on_mount(self) -> None:
        self.update_stats()

    def update_stats(self) -> None:
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()

            # Get stats
            c.execute("SELECT COUNT(*) FROM git_commits")
            total_commits = c.fetchone()[0]

            c.execute("SELECT COUNT(*) FROM tracked_repos WHERE active = 1")
            active_repos = c.fetchone()[0]

            c.execute("SELECT SUM(insertions), SUM(deletions) FROM git_commits")
            insertions, deletions = c.fetchone()

            c.execute("""
                SELECT COUNT(*) FROM git_commits
                WHERE timestamp >= date('now', '-7 days')
            """)
            recent_commits = c.fetchone()[0]

            conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            # Database might not be initialized
            total_commits = 0
            active_repos = 0
            insertions = 0
            deletions = 0
            recent_commits = 0

        # Build stats display
        table = RichTable.grid(padding=1)
        table.add_column(style="cyan", justify="right")
        table.add_column(style="white")

        table.add_row("📊 Total Commits:", str(total_commits))
        table.add_row("📁 Active Repos:", str(active_repos))
        table.add_row("➕ Lines Added:", f"{insertions or 0:,}")
        table.add_row("➖ Lines Deleted:", f"{deletions or 0:,}")
        table.add_row("🔥 Last 7 Days:", str(recent_commits))

        panel = Panel(table, title="[bold]Statistics[/]", border_style="cyan")
        self.update(panel)


class CommitList(ListView):
    """Enhanced commit list with better display"""

    commits = reactive([])

    def __init__(self, auto_load: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.auto_load = auto_load

    async def on_mount(self) -> None:
        if self.auto_load:
            await self.load_commits()

    async def watch_commits(self, new_commits: list) -> None:
        """Update the list view when commits data changes"""
        await self.clear()
        if not new_commits:
            await self.append(ListItem(Label("[dim]No commits found[/]")))
        else:
            for commit in new_commits:
                await self.append(CommitListItem(commit))

    async def load_commits(self, limit: int = 50) -> None:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            c.execute("""
                SELECT
                    c.id, c.short_hash, c.message, c.timestamp,
                    c.files_changed, r.repo_name
                FROM git_commits c
                JOIN tracked_repos r ON c.repo_id = r.id
                WHERE r.active = 1
                ORDER BY c.timestamp DESC
                LIMIT ?
            """, (limit,))

            # This assignment will trigger watch_commits
            self.commits = [dict(row) for row in c.fetchall()]
            conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            self.commits = []

    def get_selected_commit(self):
        """Get currently selected commit"""
        if self.highlighted_child and hasattr(self.highlighted_child, 'commit_data'):
            return self.highlighted_child.commit_data
        return None


class SearchPanel(Container):
    """Search interface"""

    CSS = """
    SearchPanel {
        layout: horizontal;
        height: 100%;
    }

    .search-sidebar {
        width: 35%;
        height: 100%;
        border-right: solid $primary;
        padding: 1;
    }

    #search-inputs {
        height: auto;
        margin-bottom: 1;
    }

    #search-inputs Input {
        margin-bottom: 1;
    }

    #search-results-list {
        height: 1fr;
        border-top: solid $primary;
    }

    #search-code-viewer {
        width: 65%;
        height: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(classes="search-sidebar"):
            with Vertical(id="search-inputs"):
                yield Label("[bold cyan]Search Commits[/]")
                yield Input(placeholder="Search message or code...", id="search-input")
                yield Input(placeholder="Repo filter (optional)...", id="repo-input")
                yield Button("Search", variant="primary", id="search-btn")
            yield CommitList(id="search-results-list", auto_load=False)
        
        yield CodeViewer(id="search-code-viewer")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Trigger search when Enter is pressed in input fields"""
        self.trigger_search()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "search-btn":
            self.trigger_search()

    async def trigger_search(self) -> None:
        query = self.query_one("#search-input", Input).value
        repo = self.query_one("#repo-input", Input).value
        
        print(f"DEBUG SEARCH: trigger_search called. Query='{query}', Repo='{repo}'")

        if not query and not repo:
            self.app.notify("Please enter a search term or repo filter", severity="warning")
            return
        
        self.app.notify(f"Searching for '{query}' in repo '{repo or 'all'}'...", severity="information")
        
        # Show loading state in the list
        list_view = self.query_one("#search-results-list", CommitList)
        list_view.commits = [] # Clear existing
        await list_view.append(ListItem(Label("[yellow]Searching...[/]"))) # Add loading message

        # Run search in background
        self.run_worker(self.perform_search(query, repo))

    async def perform_search(self, query: str, repo: str) -> None:
        print(f"DEBUG SEARCH: perform_search called. Query='{query}', Repo='{repo}'")
        results = await asyncio.to_thread(search_commits, query=query, repo_name=repo, limit=50)
        print(f"DEBUG SEARCH: perform_search received {len(results)} results.")

        list_view = self.query_one("#search-results-list", CommitList)
        list_view.commits = results

        if not results:
            self.app.notify("No commits found matching your criteria", severity="information")
        else:
            self.app.notify(f"Found {len(results)} commits.", severity="information")


class CommitListItem(ListItem):
    """Single commit list item"""

    def __init__(self, commit_data: dict):
        super().__init__()
        self.commit_data = commit_data

    def compose(self) -> ComposeResult:
        commit = self.commit_data
        date = commit['timestamp'].split('T')[0]

        # Format: [hash] message - repo (date)
        msg = commit['message'][:60]
        if len(commit['message']) > 60:
            msg += "..."

        text = f"[yellow]{commit['short_hash']}[/] {msg} [dim]- {commit['repo_name']} ({date})[/]"
        yield Label(text, markup=True)


class CodeViewer(ScrollableContainer):
    """Code viewer with syntax highlighting"""

    code = reactive("")
    language = reactive("python")
    current_files = reactive([])
    current_file_index = reactive(0)

    def compose(self) -> ComposeResult:
        yield Static("Select a commit to view code", id="code-display")

    def watch_code(self, new_code: str) -> None:
        widget = self.query_one("#code-display", Static)

        if not new_code:
            widget.update("No code to display")
            return

        try:
            syntax = Syntax(
                new_code,
                self.language,
                theme="monokai",
                line_numbers=True,
                word_wrap=False
            )
            widget.update(syntax)
        except:
            widget.update(new_code)

    def show_commit_code(self, commit_hash: str) -> None:
        details = get_commit_details(commit_hash)

        if not details or not details.get('changes'):
            self.code = "No code changes in this commit"
            self.current_files = []
            return

        self.current_files = details['changes']
        self.current_file_index = 0
        self._show_file(0)

    def _show_file(self, index: int) -> None:
        if not self.current_files or index >= len(self.current_files):
            return

        change = self.current_files[index]
        self.language = change.get('language', 'text')

        if change.get('diff_text'):
            self.code = change['diff_text']
        elif change.get('code_after'):
            self.code = change['code_after']
        else:
            self.code = "No code available"

        # Update border title
        total = len(self.current_files)
        self.border_title = f"Code: {change['file_path']} [{index+1}/{total}]"

    def next_file(self) -> None:
        if self.current_file_index < len(self.current_files) - 1:
            self.current_file_index += 1
            self._show_file(self.current_file_index)

    def prev_file(self) -> None:
        if self.current_file_index > 0:
            self.current_file_index -= 1
            self._show_file(self.current_file_index)


class AnalysisDisplay(ScrollableContainer):
    """Display AI analysis results"""

    analysis = reactive(None)

    def compose(self) -> ComposeResult:
        yield Static("Press 'a' to analyze selected commit", id="analysis-display")

    def watch_analysis(self, new_analysis) -> None:
        widget = self.query_one("#analysis-display", Static)

        if not new_analysis:
            widget.update("No analysis available")
            return

        lines = []

        if new_analysis.get('summary'):
            lines.append("[bold cyan]Summary:[/]")
            lines.append(new_analysis['summary'])
            lines.append("")

        if new_analysis.get('issues'):
            lines.append(f"[bold red]Issues Found ({len(new_analysis['issues'])}):[/]")
            for i, issue in enumerate(new_analysis['issues'][:10], 1):
                lines.append(f"  {i}. {issue}")
            if len(new_analysis['issues']) > 10:
                lines.append(f"  [dim]...and {len(new_analysis['issues']) - 10} more[/]")
            lines.append("")

        if new_analysis.get('suggestions'):
            lines.append(f"[bold green]Suggestions ({len(new_analysis['suggestions'])}):[/]")
            for i, sug in enumerate(new_analysis['suggestions'][:10], 1):
                lines.append(f"  {i}. {sug}")
            if len(new_analysis['suggestions']) > 10:
                lines.append(f"  [dim]...and {len(new_analysis['suggestions']) - 10} more[/]")
            lines.append("")

        if new_analysis.get('quality_score'):
            score = new_analysis['quality_score']
            color = "green" if score >= 70 else "yellow" if score >= 50 else "red"
            lines.append(f"[bold]Quality Score:[/] [{color}]{score}/100[/]")

        text = Text.from_markup("\n".join(lines))
        widget.update(text)

    def show_loading(self) -> None:
        widget = self.query_one("#analysis-display", Static)
        widget.update("[yellow]⟳ Analyzing...[/]")

    def show_error(self, error: str) -> None:
        widget = self.query_one("#analysis-display", Static)
        widget.update(f"[red]Error:[/] {error}")


class ReviewWorkflow(VerticalScroll):
    """Complete review workflow interface"""

    review_state = reactive("idle")  # idle, running, complete
    review_data = reactive(None)

    def compose(self) -> ComposeResult:
        yield Static(id="review-header")
        yield Static(id="review-progress")
        yield Static(id="review-results")
        yield Horizontal(
            Button("Start New Review", variant="primary", id="new-review-btn"),
            Button("Export Markdown", variant="default", id="export-md-btn"),
            Button("Export JSON", variant="default", id="export-json-btn"),
            id="review-actions"
        )

    def on_mount(self) -> None:
        self.update_display()

    def watch_review_state(self, new_state: str) -> None:
        self.update_display()

    def update_display(self) -> None:
        header = self.query_one("#review-header", Static)
        progress = self.query_one("#review-progress", Static)
        results = self.query_one("#review-results", Static)

        if self.review_state == "idle":
            header.update("[bold cyan]Code Review Workflow[/]\n\nPress 'r' or click 'Start New Review' to begin")
            progress.update("")
            results.update("")

        elif self.review_state == "running":
            header.update("[bold cyan]Running Code Review...[/]")
            progress.update("[yellow]⟳ Review in progress...[/]")
            results.update("")

        elif self.review_state == "complete" and self.review_data:
            self.show_results()

    def show_results(self) -> None:
        if not self.review_data:
            return

        header = self.query_one("#review-header", Static)
        results = self.query_one("#review-results", Static)
        progress = self.query_one("#review-progress", Static)

        review = self.review_data

        # Header
        header.update(f"[bold cyan]Review Complete: {review['topic']}[/]")
        progress.update("")

        # Build results display
        lines = []

        # Summary
        lines.append("[bold]Summary:[/]")
        lines.append(f"  • Commits analyzed: {review.get('commits_found', 0)}")
        lines.append(f"  • Web sources: {review.get('scraped_sources', 0)}")
        lines.append(f"  • Best practices found: {review.get('web_practices_found', 0)}")
        lines.append("")

        # Your code analysis
        your_analysis = review.get('your_analysis', {})
        if your_analysis.get('issues'):
            lines.append(f"[bold red]Your Code - Issues ({len(your_analysis['issues'])}):[/]")
            for i, issue in enumerate(your_analysis['issues'][:5], 1):
                lines.append(f"  {i}. {issue}")
            if len(your_analysis['issues']) > 5:
                lines.append(f"  [dim]...and {len(your_analysis['issues']) - 5} more[/]")
            lines.append("")

        # Comparison
        comparison = review.get('comparison', {})

        if comparison.get('matches'):
            lines.append(f"[bold green]✓ Good Practices You're Following ({len(comparison['matches'])}):[/]")
            for match in comparison['matches'][:3]:
                lines.append(f"  • {match}")
            lines.append("")

        if comparison.get('gaps'):
            lines.append(f"[bold yellow]⚠ Gaps to Address ({len(comparison['gaps'])}):[/]")
            for gap in comparison['gaps'][:5]:
                severity = gap.get('severity', 'medium')
                icon = "🔴" if severity == 'high' else "🟡"
                lines.append(f"  {icon} {gap['practice']}")
            lines.append("")

        # Recommendations
        if comparison.get('recommendations'):
            lines.append(f"[bold cyan]💡 Top Recommendations ({len(comparison['recommendations'])}):[/]")
            for i, rec in enumerate(comparison['recommendations'][:5], 1):
                lines.append(f"  {i}. {rec['title']}")
                lines.append(f"     {rec['description'][:80]}...")
            lines.append("")

        lines.append(f"[dim]Review ID: {review.get('id')}[/]")

        results.update(Text.from_markup("\n".join(lines)))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        try:
            if event.button.id == "new-review-btn":
                self.app.action_start_review()
            elif event.button.id == "export-md-btn":
                self.export_review("markdown")
            elif event.button.id == "export-json-btn":
                self.export_review("json")
        except Exception as e:
            logger.error(f"Error in on_button_pressed: {e}")
            self.app.notify(f"Error: {e}", severity="error")

    def export_review(self, format: str) -> None:
        if not self.review_data:
            self.app.notify("No review to export", severity="warning")
            return

        from devlog.export.report_generator import ReportGenerator

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = 'md' if format == 'markdown' else 'json'
        filename = f"review_{self.review_data.get('id', 'unknown')}_{timestamp}.{ext}"

        generator = ReportGenerator()
        generator.save_report(self.review_data, filename, format)

        self.app.notify(f"✓ Exported to {filename}", severity="information")


class WebSearchPanel(VerticalScroll):
    """Web search interface"""

    results = reactive([])

    def compose(self) -> ComposeResult:
        yield Label("[bold cyan]Web Search[/]\n\nPress 'w' to search the web")
        yield Static(id="search-results")

    def show_results(self, results: list) -> None:
        self.results = results
        widget = self.query_one("#search-results", Static)

        if not results:
            widget.update("[yellow]No results found[/]")
            return

        lines = []
        for i, result in enumerate(results[:10], 1):
            lines.append(f"[bold cyan]{i}. [{result['score']:.2f}] {result['title']}[/]")
            lines.append(f"   [dim]{result['source']}[/]")
            lines.append(f"   {result['url']}")
            lines.append(f"   {result['snippet'][:150]}...")
            lines.append("")

        widget.update(Text.from_markup("\n".join(lines)))


# ==================== MAIN APP ====================

class DevLogTUI(App):
    """Enhanced DevLog TUI Application"""

    CSS = """
    Screen {
        background: $surface;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 1 2;
    }

    #dashboard-content {
        layout: vertical;
    }

    #commits-layout {
        layout: horizontal;
        height: 1fr;
    }

    #commit-list-container {
        width: 35%;
        border: solid $primary;
    }

    #code-viewer {
        width: 40%;
        border: solid $primary;
    }

    #analysis-panel {
        width: 25%;
        border: solid $primary;
    }

    #review-actions {
        height: 3;
        align: center middle;
        margin: 1 0;
    }

    #review-actions Button {
        margin: 0 1;
    }

    ListView {
        height: 100%;
    }
    """

    BINDINGS = [
        # Navigation
        Binding("1", "switch_tab('dashboard')", "Dashboard", show=True),
        Binding("2", "switch_tab('commits')", "Commits", show=True),
        Binding("3", "switch_tab('review')", "Review", show=True),
        Binding("4", "switch_tab('search')", "Search", show=True),
        Binding("5", "switch_tab('web')", "Web", show=True),

        # Actions
        Binding("a", "analyze", "Analyze", show=True),
        Binding("r", "start_review", "Review", show=True),
        Binding("ctrl+s", "web_search", "Web Search", show=True),
        Binding("n", "next_file", "Next File", show=True),
        Binding("p", "prev_file", "Prev File", show=True),

        # General
        Binding("?", "help", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()

        with TabbedContent(initial="dashboard"):
            # Dashboard Tab
            with TabPane("Dashboard", id="dashboard"):
                with Vertical(id="dashboard-content"):
                    yield StatsPanel()
                    yield Label("\n[bold cyan]Quick Actions:[/]")
                    yield Label("  1. Press [bold]2[/] to browse commits")
                    yield Label("  2. Press [bold]r[/] to start a code review")
                    yield Label("  3. Press [bold]w[/] to search the web")
                    yield Label("  4. Press [bold]a[/] to analyze a commit")

            # Commits Tab
            with TabPane("Commits", id="commits"):
                with Horizontal(id="commits-layout"):
                    with Container(id="commit-list-container"):
                        yield CommitList(id="commit-list")
                    yield CodeViewer(id="code-viewer")
                    yield AnalysisDisplay(id="analysis-panel")

            # Review Tab
            with TabPane("Review", id="review"):
                yield ReviewWorkflow(id="review-workflow")

            # Search Tab
            with TabPane("Search", id="search"):
                yield SearchPanel(id="search-panel")

            # Web Tab
            with TabPane("Web", id="web"):
                yield WebSearchPanel(id="web-panel")

        yield Footer()

    def on_mount(self) -> None:
        self.title = "DevLog - Code Review Assistant"
        self.sub_title = "Enhanced TUI"

        # Check Ollama
        if not test_connection():
            self.notify(
                "⚠️ Ollama not running - analysis features disabled",
                severity="warning",
                timeout=5
            )

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Handle commit selection"""
        try:
            if event.list_view.id == "commit-list":
                commit_list = self.query_one("#commit-list", CommitList)
                commit = commit_list.get_selected_commit()

                if commit:
                    code_viewer = self.query_one("#code-viewer", CodeViewer)
                    code_viewer.show_commit_code(commit['short_hash'])

                    # Clear previous analysis
                    analysis = self.query_one("#analysis-panel", AnalysisDisplay)
                    analysis.analysis = None
            
            elif event.list_view.id == "search-results-list":
                commit_list = self.query_one("#search-results-list", CommitList)
                commit = commit_list.get_selected_commit()
                
                if commit:
                    code_viewer = self.query_one("#search-code-viewer", CodeViewer)
                    code_viewer.show_commit_code(commit['short_hash'])
        except Exception as e:
            logger.error(f"Error in on_list_view_highlighted: {e}")
            self.app.notify(f"Error: {e}", severity="error")

    # ==================== ACTIONS ====================

    def action_switch_tab(self, tab_id: str) -> None:
        """Switch to a specific tab"""
        tabs = self.query_one(TabbedContent)
        tabs.active = tab_id

    @work(exclusive=True)
    async def action_analyze(self) -> None:
        """Analyze selected commit"""
        try:
            commit_list = self.query_one(CommitList)
        except:
            self.notify("No commit list available", severity="warning")
            return

        commit = commit_list.get_selected_commit()
        if not commit:
            self.notify("No commit selected", severity="warning")
            return

        if not test_connection():
            self.notify("Ollama not running", severity="error")
            return

        analysis_panel = self.query_one("#analysis-panel", AnalysisDisplay)
        analysis_panel.show_loading()

        analyzer = CodeAnalyzer()

        try:
            result = await analyzer.analyze_commit(
                commit['short_hash'],
                'quick'
            )

            if result:
                analysis_panel.analysis = result
                self.notify("✓ Analysis complete", severity="information")
            else:
                analysis_panel.show_error("Analysis failed")
        except Exception as e:
            analysis_panel.show_error(str(e))
            self.notify(f"Analysis error: {e}", severity="error")

    def action_start_review(self) -> None:
        """Start code review workflow"""
        
        def on_review_input(result):
            if result:
                topic, language, commits = result
                self.run_review(topic, language, commits)
                
        self.push_screen(ReviewInputModal(), on_review_input)

    @work(exclusive=True)
    async def run_review(self, topic: str, language: str, commits: int) -> None:
        """Run the full review pipeline"""
        # Switch to review tab
        self.action_switch_tab("review")

        review_workflow = self.query_one("#review-workflow", ReviewWorkflow)
        review_workflow.review_state = "running"

        if not test_connection():
            self.notify("Ollama not running", severity="error")
            review_workflow.review_state = "idle"
            return

        pipeline = ReviewPipeline()

        try:
            # Run review in background thread
            result = await pipeline.review_topic(
                topic,
                language,
                commits,
                deep_analysis=False
            )

            if 'error' in result:
                self.notify(f"Review error: {result['error']}", severity="error")
                review_workflow.review_state = "idle"
            else:
                review_workflow.review_data = result
                review_workflow.review_state = "complete"
                self.notify("✓ Review complete!", severity="information")

        except Exception as e:
            self.notify(f"Review failed: {e}", severity="error")
            review_workflow.review_state = "idle"

    def action_web_search(self) -> None:
        """Open web search modal"""
        
        def on_search(query):
            if query:
                self.perform_web_search(query)
                
        self.push_screen(WebSearchModal(), on_search)

    @work(exclusive=True)
    async def perform_web_search(self, query: str) -> None:
        """Perform web search"""
        self.action_switch_tab("web")

        web_panel = self.query_one("#web-panel", WebSearchPanel)
        widget = web_panel.query_one("#search-results", Static)
        widget.update("[yellow]⟳ Searching...[/]")

        searcher = WebSearcher()

        try:
            results = await asyncio.to_thread(searcher.search, query, 10)
            web_panel.show_results(results)
        except Exception as e:
            widget.update(f"[red]Search failed:[/] {e}")

    def action_next_file(self) -> None:
        """Show next file in commit"""
        try:
            code_viewer = self.query_one("#code-viewer", CodeViewer)
            code_viewer.next_file()
        except:
            pass

    def action_prev_file(self) -> None:
        """Show previous file in commit"""
        try:
            code_viewer = self.query_one("#code-viewer", CodeViewer)
            code_viewer.prev_file()
        except:
            pass

    def action_help(self) -> None:
        """Show help"""
        help_text = """[bold cyan]DevLog TUI - Help[/]

[bold]Tabs:[/]
  1-5         Switch between tabs

[bold]Commits:[/]
  ↑/↓         Navigate commit list
  n/p         Next/previous file
  a           Analyze selected commit

[bold]Review:[/]
  r           Start new code review

[bold]Web:[/]
  w           Search the web

[bold]Other:[/]
  ?           Show this help
  q           Quit application
        """
        self.notify(help_text, timeout=10)


def run_tui():
    """Entry point for enhanced TUI"""
    app = DevLogTUI()
    app.run()


def main():
    run_tui()


if __name__ == "__main__":
    run_tui()
