"""
DevLog TUI - Terminal User Interface with Neovim-like keybindings
Fixed version with proper keyboard navigation
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
from devlog.search.web_search import WebSearcher
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
        self.can_focus = True

    def compose(self) -> ComposeResult:
        yield ListView(id="commit-list")

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
        list_view = self.query_one("#commit-list", ListView)
        await list_view.clear()

        for commit in self.commits:
            await list_view.append(CommitListItem(commit))

    async def search_commits(self, query: str):
        """Search commits by keyword"""
        from devlog.core.search import search_commits

        results = search_commits(query=query, limit=50)
        self.commits = results

        # Update ListView
        list_view = self.query_one("#commit-list", ListView)
        await list_view.clear()

        for commit in self.commits:
            await list_view.append(CommitListItem(commit))

        self.app.notify(f"Found {len(results)} commits", severity="information")

    def get_selected_commit(self):
        """Get currently selected commit"""
        list_view = self.query_one("#commit-list", ListView)
        if list_view.highlighted_child:
            return list_view.highlighted_child.commit_data
        return None


class CodeViewer(ScrollableContainer):
    """Middle panel: Code diff viewer with file switching"""

    code = reactive("")
    language = reactive("python")
    current_files = []
    current_file_index = 0

    def __init__(self):
        super().__init__()
        self.border_title = "Code"
        self.can_focus = True

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
            self.current_files = []
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
        else:
            self.app.notify("Last file", severity="information")

    def prev_file(self):
        """Show previous file"""
        if self.current_file_index > 0:
            self.current_file_index -= 1
            self._show_file(self.current_file_index)
        else:
            self.app.notify("First file", severity="information")


class AnalysisPanel(ScrollableContainer):
    """Right panel: AI analysis results"""

    analysis = reactive(None)

    def __init__(self):
        super().__init__()
        self.border_title = "Analysis"
        self.can_focus = True

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


class WebSearchPanel(ScrollableContainer):
    """Web Search results panel"""

    results = reactive([])

    def __init__(self):
        super().__init__()
        self.border_title = "Web Search"
        self.can_focus = True
        self.display = False  # Hidden by default

    def compose(self) -> ComposeResult:
        yield Static("Press 'w' to search the web", id="web-content")

    def show_results(self, results):
        """Display search results"""
        widget = self.query_one("#web-content", Static)

        if not results:
            widget.update("No results found")
            return

        lines = []
        for i, res in enumerate(results, 1):
            lines.append(f"[bold cyan]{i}. {res['title']}[/]")
            lines.append(f"[dim]{res['source']}[/]")
            lines.append(f"{res['snippet']}")
            lines.append("")

        text = Text.from_markup("\n".join(lines))
        widget.update(text)

    def show_loading(self):
        widget = self.query_one("#web-content", Static)
        widget.update("[yellow]Searching...[/]")


class SearchBar(Input):
    """Search input bar"""

    def __init__(
        self,
        placeholder: str = "Search commits... (press / to focus)",
        *,
        id: str | None = None,
        classes: str | None = None
    ):
        super().__init__(placeholder=placeholder, id=id, classes=classes)


class StatusBar(Static):
    """Bottom status bar with hints"""

    mode = reactive("normal")

    def compose(self) -> ComposeResult:
        yield Label(self.get_status_text(), markup=True, id="status-label")

    def watch_mode(self, new_mode: str):
        """Update status text when mode changes"""
        if not self.is_mounted:
            return  # do nothing until children are mounted

        label = self.query_one("#status-label", Label)
        label.update(self.get_status_text())

    def get_status_text(self) -> str:
        """Generate status text based on mode"""
        if self.mode == "search":
            return "[yellow]SEARCH MODE[/] [dim]Enter: search, Esc: cancel[/]"
        elif self.mode == "web_search":
            return "[yellow]WEB SEARCH[/] [dim]Enter: search query, Esc: cancel[/]"
        else:
            return "[dim]j/k[/] Navigate  [dim]/[/] Search Commits  [dim]w[/] Web Search  [dim]a[/] Analyze  [dim]tab[/] Switch Panel  [dim]q[/] Quit"


class DevLogTUI(App):
    """Main TUI application with Neovim-like keybindings"""

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-container {
        layout: horizontal;
        height: 1fr;
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

    WebSearchPanel {
        width: 30%;
        border: solid $accent;
        display: none; 
    }

    WebSearchPanel.visible {
        display: block;
    }

    SearchBar {
        dock: top;
        height: 3;
        border: solid $accent;
        display: none;
    }

    SearchBar.visible {
        display: block;
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
    
    #web-content {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }

    .focused {
        border: solid $success;
    }
    """

    BINDINGS = [
        # Vim-like navigation
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "goto_top", "Top", show=False),
        Binding("shift+g", "goto_bottom", "Bottom", show=False),
        Binding("ctrl+d", "half_page_down", "Half Page Down", show=False),
        Binding("ctrl+u", "half_page_up", "Half Page Up", show=False),

        # File navigation
        Binding("n", "next_file", "Next File", show=True),
        Binding("p", "prev_file", "Prev File", show=True),

        # Actions
        Binding("a", "analyze", "Analyze", show=True),
        Binding("r", "review", "Review", show=True),
        Binding("/", "search", "Search Commits", show=True),
        Binding("w", "web_search", "Web Search", show=True),
        Binding("escape", "cancel", "Cancel", show=False),

        # Panel switching
        Binding("tab", "next_panel", "Next Panel", show=True),
        Binding("shift+tab", "prev_panel", "Prev Panel", show=False),
        Binding("1", "focus_timeline", "Timeline", show=False),
        Binding("2", "focus_code", "Code", show=False),
        Binding("3", "focus_analysis", "Analysis", show=False),
        Binding("4", "focus_web", "Web", show=False),

        # Selection
        Binding("enter", "select", "Select", show=False),

        # Help and quit
        Binding("?", "help", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self):
        super().__init__()
        self.search_mode = False
        self.web_search_mode = False
        self.panels = []
        self.current_panel_index = 0

    def compose(self) -> ComposeResult:
        """Create child widgets"""
        yield Header()
        yield SearchBar(id="search-bar")

        with Container(id="main-container"):
            yield CommitTimeline()
            yield CodeViewer()
            yield AnalysisPanel()
            yield WebSearchPanel()

        yield StatusBar()
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize when app starts"""
        self.title = "DevLog - Code Review Assistant"
        self.sub_title = "Personal Code Memory"

        # Store panel references
        self.panels = [
            self.query_one(CommitTimeline),
            self.query_one(CodeViewer),
            self.query_one(AnalysisPanel),
            self.query_one(WebSearchPanel)
        ]

        # Focus first panel
        self.panels[0].focus()

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

            # Clear previous analysis
            analysis_panel = self.query_one(AnalysisPanel)
            analysis_panel.analysis = None

    # Vim-like navigation actions
    async def action_cursor_down(self) -> None:
        """Move cursor down (j)"""
        if self.search_mode or self.web_search_mode:
            return

        try:
            list_view = self.query_one("#commit-list", ListView)
            list_view.action_cursor_down()
        except:
            pass

    async def action_cursor_up(self) -> None:
        """Move cursor up (k)"""
        if self.search_mode or self.web_search_mode:
            return

        try:
            list_view = self.query_one("#commit-list", ListView)
            list_view.action_cursor_up()
        except:
            pass

    async def action_goto_top(self) -> None:
        """Go to top (g)"""
        if self.search_mode or self.web_search_mode:
            return

        try:
            list_view = self.query_one("#commit-list", ListView)
            list_view.index = 0
        except:
            pass

    async def action_goto_bottom(self) -> None:
        """Go to bottom (G)"""
        if self.search_mode or self.web_search_mode:
            return

        try:
            list_view = self.query_one("#commit-list", ListView)
            list_view.index = len(list_view.children) - 1
        except:
            pass

    async def action_half_page_down(self) -> None:
        """Scroll half page down (Ctrl+d)"""
        if self.search_mode or self.web_search_mode:
            return

        focused = self.focused
        if isinstance(focused, ScrollableContainer):
            focused.scroll_page_down()

    async def action_half_page_up(self) -> None:
        """Scroll half page up (Ctrl+u)"""
        if self.search_mode or self.web_search_mode:
            return

        focused = self.focused
        if isinstance(focused, ScrollableContainer):
            focused.scroll_page_up()

    # File navigation
    async def action_next_file(self) -> None:
        """Show next file in commit (n)"""
        code_viewer = self.query_one(CodeViewer)
        code_viewer.next_file()

    async def action_prev_file(self) -> None:
        """Show previous file in commit (p)"""
        code_viewer = self.query_one(CodeViewer)
        code_viewer.prev_file()

    # Panel switching
    async def action_next_panel(self) -> None:
        """Focus next panel (Tab)"""
        # If we have 3 panels visible (normal mode), cycle 3
        # If web panel is visible (we'll implement toggle), maybe 4?
        # For simplicity, let's keep web panel hidden unless focused or searched
        
        limit = 4 if self.panels[3].has_class("visible") else 3
        self.current_panel_index = (self.current_panel_index + 1) % limit
        self.panels[self.current_panel_index].focus()

    async def action_prev_panel(self) -> None:
        """Focus previous panel (Shift+Tab)"""
        limit = 4 if self.panels[3].has_class("visible") else 3
        self.current_panel_index = (self.current_panel_index - 1) % limit
        self.panels[self.current_panel_index].focus()

    async def action_focus_timeline(self) -> None:
        """Focus timeline panel (1)"""
        self.current_panel_index = 0
        self.panels[0].focus()

    async def action_focus_code(self) -> None:
        """Focus code panel (2)"""
        self.current_panel_index = 1
        self.panels[1].focus()

    async def action_focus_analysis(self) -> None:
        """Focus analysis panel (3)"""
        self.current_panel_index = 2
        self.panels[2].focus()

    async def action_focus_web(self) -> None:
        """Focus web panel (4)"""
        # Toggle visibility
        web_panel = self.panels[3]
        analysis_panel = self.panels[2]
        
        web_panel.add_class("visible")
        analysis_panel.display = False # Swap analysis with web to save space?
        # Or just have it overlay/replace one
        
        # Let's replace Analysis with Web for now or just cycle
        # CSS handles display:none for default
        
        # Simple toggle: show web, hide analysis
        web_panel.add_class("visible")
        analysis_panel.display = False
        
        self.current_panel_index = 3
        web_panel.focus()

    # Search
    async def action_search(self) -> None:
        """Enter commit search mode (/)"""
        if self.search_mode or self.web_search_mode:
            return

        self.search_mode = True
        search_bar = self.query_one("#search-bar", SearchBar)
        search_bar.placeholder = "Search commits..."
        search_bar.add_class("visible")
        search_bar.focus()

        status_bar = self.query_one(StatusBar)
        status_bar.mode = "search"
        
    async def action_web_search(self) -> None:
        """Enter web search mode (w)"""
        if self.search_mode or self.web_search_mode:
            return

        self.web_search_mode = True
        search_bar = self.query_one("#search-bar", SearchBar)
        search_bar.placeholder = "Search web (e.g. 'python best practices')..."
        search_bar.add_class("visible")
        search_bar.focus()

        status_bar = self.query_one(StatusBar)
        status_bar.mode = "web_search"
        
        # Show web panel
        web_panel = self.panels[3]
        analysis_panel = self.panels[2]
        web_panel.add_class("visible")
        analysis_panel.display = False

    async def action_cancel(self) -> None:
        """Cancel search mode (Esc)"""
        if self.search_mode or self.web_search_mode:
            self.search_mode = False
            self.web_search_mode = False
            search_bar = self.query_one("#search-bar", SearchBar)
            search_bar.remove_class("visible")
            search_bar.value = ""

            status_bar = self.query_one(StatusBar)
            status_bar.mode = "normal"

            # Focus back to timeline
            self.panels[0].focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search submission"""
        query = event.value
        if not query:
            await self.action_cancel()
            return
            
        if self.search_mode:
            timeline = self.query_one(CommitTimeline)
            await timeline.search_commits(query)
            await self.action_cancel()
            
        elif self.web_search_mode:
            web_panel = self.query_one(WebSearchPanel)
            web_panel.show_loading()
            
            # Execute search
            searcher = WebSearcher()
            try:
                # Run in background to not block UI
                results = await asyncio.to_thread(searcher.search, query, 10)
                web_panel.show_results(results)
            except Exception as e:
                web_panel.show_results([{"title": "Error", "source": "System", "snippet": str(e)}])
                
            await self.action_cancel()
            
            # Keep web panel focused
            web_panel.focus()
            self.current_panel_index = 3

    # Analysis
    async def action_analyze(self) -> None:
        """Analyze selected commit (a)"""
        timeline = self.query_one(CommitTimeline)
        commit = timeline.get_selected_commit()

        if not commit:
            self.notify("No commit selected", severity="warning")
            return

        # Check Ollama
        if not test_connection():
            self.notify("Ollama not running - start with 'ollama serve'", severity="error")
            return

        # Ensure analysis panel is visible
        analysis_panel = self.query_one(AnalysisPanel)
        web_panel = self.query_one(WebSearchPanel)
        analysis_panel.display = True
        web_panel.remove_class("visible")
        
        analysis_panel.show_loading()

        # Run analysis in background
        analyzer = CodeAnalyzer()

        try:
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
        """Full review pipeline (r)"""
        self.notify("Use CLI: devlog review <topic>", severity="information")

    async def action_select(self) -> None:
        """Select current item (Enter)"""
        try:
            list_view = self.query_one("#commit-list", ListView)
            list_view.action_select_cursor()
        except:
            pass

    async def action_help(self) -> None:
        """Show help (?)"""
        help_text = """[bold cyan]DevLog TUI - Neovim-style Keybindings[/]

[bold]Navigation:[/]
  j/k         Move down/up
  g/G         Go to top/bottom
  Ctrl+d/u    Half page down/up

[bold]Panels:[/]
  Tab         Next panel
  Shift+Tab   Previous panel
  1/2/3       Jump to Timeline/Code/Analysis
  4           Jump to Web Search

[bold]Files:[/]
  n/p         Next/previous file in commit

[bold]Actions:[/]
  a           Analyze commit (with Ollama)
  r           Full review
  /           Search commits
  w           Web Search
  Enter       Select commit
  Esc         Cancel search

[bold]Other:[/]
  ?           Show this help
  q           Quit
        """

        self.notify(help_text, timeout=15)


def run_tui():
    """Entry point for TUI"""
    app = DevLogTUI()
    app.run()

def main():
    run_tui()

if __name__ == "__main__":
    run_tui()
