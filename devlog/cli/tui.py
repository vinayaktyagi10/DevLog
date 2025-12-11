"""
DevLog TUI - Terminal User Interface using Textual
"""
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, ListView, ListItem, Label, Input, Button
from textual.binding import Binding
from textual.reactive import reactive
from textual import events
from rich.syntax import Syntax
from rich.panel import Panel
from rich.text import Text
import sqlite3
from datetime import datetime
from devlog.paths import DB_PATH
from devlog.core.search import get_commit_details
from devlog.analysis.analyzer import CodeAnalyzer
from devlog.analysis.llm import test_connection
import asyncio


class CommitListItem(ListItem):
    """A list item for displaying a commit"""

    def __init__(self, commit_data: dict):
        super().__init__()
        self.commit_data = commit_data

    def compose(self) -> ComposeResult:
        commit = self.commit_data
        date = commit['timestamp'].split('T')[0]

        # Format: [•] hash - message (date)
        text = f"[cyan]{commit['short_hash']}[/] {commit['message'][:50]}"
        if len(commit['message']) > 50:
            text += "..."
        text += f" [dim]{date}[/]"

        yield Label(text, markup=True)


class CommitTimeline(ScrollableContainer):
    """Left panel: Scrollable commit timeline"""

    commits = reactive([])
    selected_index = reactive(0)

    def __init__(self):
        super().__init__()
        self.border_title = "Timeline"

    def compose(self) -> ComposeResult:
        yield ListView()

    async def load_commits(self, limit: int = 50):
        """Load commits from database"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT
                c.id,
                c.short_hash,
                c.message,
                c.timestamp,
                c.files_changed,
                r.repo_name
            FROM git_commits c
            JOIN tracked_repos r ON c.repo_id = r.id
            WHERE r.active = 1
            ORDER BY c.timestamp DESC
            LIMIT ?
        """, (limit,))

        self.commits = [dict(row) for row in c.fetchall()]
        conn.close()

        # Populate ListView
        list_view = self.query_one(ListView)
        await list_view.clear()

        for commit in self.commits:
            await list_view.append(CommitListItem(commit))

    def get_selected_commit(self):
        """Get currently selected commit"""
        list_view = self.query_one(ListView)
        if list_view.highlighted_child:
            return list_view.highlighted_child.commit_data
        return None


class CodeViewer(ScrollableContainer):
    """Middle panel: Code diff viewer"""

    code = reactive("")
    language = reactive("python")

    def __init__(self):
        super().__init__()
        self.border_title = "Code"

    def compose(self) -> ComposeResult:
        yield Static("Select a commit to view code", id="code-content")

    def watch_code(self, new_code: str):
        """Update displayed code when code changes"""
        code_widget = self.query_one("#code-content", Static)

        if not new_code:
            code_widget.update("No code to display")
            return

        # Syntax highlight the code
        try:
            syntax = Syntax(
                new_code,
                self.language,
                theme="monokai",
                line_numbers=True,
                word_wrap=False
            )
            code_widget.update(syntax)
        except:
            code_widget.update(new_code)

    def show_commit_code(self, commit_hash: str):
        """Display code for a commit"""
        details = get_commit_details(commit_hash)

        if not details or not details.get('changes'):
            self.code = "No code changes in this commit"
            return

        # Show first changed file
        change = details['changes'][0]
        self.language = change.get('language', 'text')

        if change.get('diff_text'):
            self.code = change['diff_text']
        elif change.get('code_after'):
            self.code = change['code_after']
        else:
            self.code = "No code available"

        # Update border title with filename
        self.border_title = f"Code: {change['file_path']}"


class AnalysisPanel(ScrollableContainer):
    """Right panel: AI analysis results"""

    analysis = reactive(None)

    def __init__(self):
        super().__init__()
        self.border_title = "Analysis"

    def compose(self) -> ComposeResult:
        yield Static("Press 'a' to analyze selected commit", id="analysis-content")

    def watch_analysis(self, new_analysis):
        """Update displayed analysis"""
        widget = self.query_one("#analysis-content", Static)

        if not new_analysis:
            widget.update("No analysis available")
            return

        # Format analysis results
        lines = []

        if new_analysis.get('summary'):
            lines.append("[bold cyan]Summary:[/]")
            lines.append(new_analysis['summary'])
            lines.append("")

        if new_analysis.get('issues'):
            lines.append("[bold red]Issues:[/]")
            for i, issue in enumerate(new_analysis['issues'][:5], 1):
                lines.append(f"  {i}. {issue}")
            if len(new_analysis['issues']) > 5:
                lines.append(f"  [dim]...and {len(new_analysis['issues']) - 5} more[/]")
            lines.append("")

        if new_analysis.get('suggestions'):
            lines.append("[bold green]Suggestions:[/]")
            for i, suggestion in enumerate(new_analysis['suggestions'][:5], 1):
                lines.append(f"  {i}. {suggestion}")
            if len(new_analysis['suggestions']) > 5:
                lines.append(f"  [dim]...and {len(new_analysis['suggestions']) - 5} more[/]")

        text = Text.from_markup("\n".join(lines))
        widget.update(text)

    def show_loading(self):
        """Show loading indicator"""
        widget = self.query_one("#analysis-content", Static)
        widget.update("[yellow]Analyzing...[/]")

    def show_error(self, error: str):
        """Show error message"""
        widget = self.query_one("#analysis-content", Static)
        widget.update(f"[red]Error:[/] {error}")


class StatusBar(Static):
    """Bottom status bar with hints"""

    def compose(self) -> ComposeResult:
        hints = "[dim]↑↓[/] Navigate  [dim]/[/] Search  [dim]a[/] Analyze  [dim]r[/] Review  [dim]Enter[/] Details  [dim]q[/] Quit"
        yield Label(hints, markup=True)


class DevLogTUI(App):
    """Main TUI application"""

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-container {
        layout: horizontal;
        height: 100%;
    }

    CommitTimeline {
        width: 30%;
        border: solid $accent;
    }

    CodeViewer {
        width: 40%;
        border: solid $accent;
    }

    AnalysisPanel {
        width: 30%;
        border: solid $accent;
    }

    StatusBar {
        dock: bottom;
        height: 1;
        background: $panel;
    }

    ListView {
        height: 100%;
    }

    ListItem {
        padding: 0 1;
    }

    ListItem:hover {
        background: $boost;
    }

    #code-content {
        width: 100%;
        height: 100%;
    }

    #analysis-content {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=False),
        Binding("a", "analyze", "Analyze", show=True),
        Binding("r", "review", "Review", show=True),
        Binding("/", "search", "Search", show=True),
        Binding("?", "help", "Help", show=True),
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select", show=False),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets"""
        yield Header()

        with Container(id="main-container"):
            yield CommitTimeline()
            yield CodeViewer()
            yield AnalysisPanel()

        yield StatusBar()
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize when app starts"""
        self.title = "DevLog - Code Review Assistant"
        self.sub_title = "Personal Code Memory"

        # Load commits
        timeline = self.query_one(CommitTimeline)
        await timeline.load_commits()

        # Check Ollama connection
        if not test_connection():
            self.notify(
                "⚠️ Ollama not running - analysis features disabled",
                severity="warning",
                timeout=5
            )

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Handle commit selection in timeline"""
        if event.item and hasattr(event.item, 'commit_data'):
            commit = event.item.commit_data

            # Update code viewer
            code_viewer = self.query_one(CodeViewer)
            code_viewer.show_commit_code(commit['short_hash'])

    async def action_analyze(self) -> None:
        """Analyze selected commit"""
        timeline = self.query_one(CommitTimeline)
        commit = timeline.get_selected_commit()

        if not commit:
            self.notify("No commit selected", severity="warning")
            return

        # Check Ollama
        if not test_connection():
            self.notify("Ollama not running - start with 'ollama serve'", severity="error")
            return

        analysis_panel = self.query_one(AnalysisPanel)
        analysis_panel.show_loading()

        # Run analysis in background
        analyzer = CodeAnalyzer()

        try:
            # Run in thread pool to avoid blocking
            result = await asyncio.to_thread(
                analyzer.analyze_commit,
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

    async def action_review(self) -> None:
        """Full review pipeline"""
        self.notify("Review feature coming in Day 7!", severity="information")

    async def action_search(self) -> None:
        """Search commits"""
        self.notify("Search feature coming in Day 7!", severity="information")

    async def action_help(self) -> None:
        """Show help"""
        help_text = """
[bold cyan]DevLog TUI Help[/]

[bold]Navigation:[/]
  ↑/↓ or j/k  - Move through commits
  Enter       - Select commit

[bold]Actions:[/]
  a           - Analyze selected commit
  r           - Full review
  /           - Search commits

[bold]Other:[/]
  ?           - Show this help
  q           - Quit
        """

        self.notify(help_text, timeout=10)

    async def action_cursor_up(self) -> None:
        """Move cursor up"""
        list_view = self.query_one(ListView)
        list_view.action_cursor_up()

    async def action_cursor_down(self) -> None:
        """Move cursor down"""
        list_view = self.query_one(ListView)
        list_view.action_cursor_down()

    async def action_select(self) -> None:
        """Select current item"""
        list_view = self.query_one(ListView)
        list_view.action_select_cursor()


class SearchInput(Input):
    """Search input at top of timeline"""

    def __init__(self):
        super().__init__(placeholder="Search commits...")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search submission"""
        query = event.value
        if query:
            timeline = self.app.query_one(CommitTimeline)
            await timeline.search_commits(query)


# Add to CommitTimeline class:
    async def search_commits(self, query: str):
        """Search commits by keyword"""
        from devlog.core.search import search_commits

        results = search_commits(query=query, limit=50)
        self.commits = results

        # Update ListView
        list_view = self.query_one(ListView)
        await list_view.clear()

        for commit in self.commits:
            await list_view.append(CommitListItem(commit))

        self.app.notify(f"Found {len(results)} commits", severity="information")


# Update DevLogTUI.compose() to include search:
    def compose(self) -> ComposeResult:
        """Create child widgets"""
        yield Header()

        with Container(id="main-container"):
            timeline_container = Vertical()
            with timeline_container:
                yield SearchInput()
                yield CommitTimeline()

            yield CodeViewer()
            yield AnalysisPanel()

        yield StatusBar()
        yield Footer()


class CodeViewer(ScrollableContainer):
    """Middle panel: Code diff viewer with file switching"""

    code = reactive("")
    language = reactive("python")
    current_files = []
    current_file_index = 0

    # ... existing code ...

    def show_commit_code(self, commit_hash: str):
        """Display code for a commit"""
        details = get_commit_details(commit_hash)

        if not details or not details.get('changes'):
            self.code = "No code changes in this commit"
            return

        self.current_files = details['changes']
        self.current_file_index = 0
        self._show_file(0)

    def _show_file(self, index: int):
        """Show specific file from current commit"""
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

        # Update title with file counter
        total = len(self.current_files)
        self.border_title = f"Code: {change['file_path']} [{index+1}/{total}]"

    def next_file(self):
        """Show next file"""
        if self.current_file_index < len(self.current_files) - 1:
            self.current_file_index += 1
            self._show_file(self.current_file_index)

    def prev_file(self):
        """Show previous file"""
        if self.current_file_index > 0:
            self.current_file_index -= 1
            self._show_file(self.current_file_index)


# Add bindings to DevLogTUI:
    BINDINGS = [
        # ... existing bindings ...
        Binding("n", "next_file", "Next File", show=True),
        Binding("p", "prev_file", "Prev File", show=True),
    ]

    async def action_next_file(self) -> None:
        """Show next file in commit"""
        code_viewer = self.query_one(CodeViewer)
        code_viewer.next_file()

    async def action_prev_file(self) -> None:
        """Show previous file in commit"""
        code_viewer = self.query_one(CodeViewer)
        code_viewer.prev_file()


def run_tui():
    """Entry point for TUI"""
    app = DevLogTUI()
    app.run()


if __name__ == "__main__":
    run_tui()
