"""
Updated Chat TUI - Integrated with enhanced chat manager and persistence
"""
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, Static, TextArea, Button, Label, ListItem, ListView
from textual.binding import Binding
from textual import work
from textual.events import Key
from textual.screen import ModalScreen
import logging
import pyperclip

from devlog.analysis.chat_manager import ChatManager
from devlog.analysis.conversation_db import ConversationManager, init_conversation_tables
from devlog.analysis.llm import test_connection

# Setup logging
logging.basicConfig(
    filename='devlog_chat_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ConversationListModal(ModalScreen):
    """Modal to show conversation history"""

    CSS = """
    ConversationListModal {
        align: center middle;
    }

    #dialog {
        width: 80;
        height: 30;
        border: thick $primary;
        background: $surface;
        padding: 1;
    }

    #conv-list {
        height: 1fr;
        margin: 1 0;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self):
        super().__init__()
        self.manager = ConversationManager()

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Label("[bold cyan]Conversation History[/]")
            yield ListView(id="conv-list")
            with Horizontal():
                yield Button("Load", variant="primary", id="load-btn")
                yield Button("Delete", variant="error", id="delete-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_mount(self):
        self._load_conversations()

    def _load_conversations(self):
        conversations = self.manager.list_conversations(limit=50)

        list_view = self.query_one("#conv-list", ListView)
        list_view.clear()

        for conv in conversations:
            title = conv['title']
            date = conv['last_message_at'].split('T')[0]
            count = conv['message_count']

            label = Label(f"{title} ({count} msgs, {date})")
            label.conversation_id = conv['id']

            list_view.append(ListItem(label))

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "load-btn":
            selected = self.query_one("#conv-list", ListView).highlighted_child
            if selected and hasattr(selected.children[0], 'conversation_id'):
                self.dismiss(('load', selected.children[0].conversation_id))
        elif event.button.id == "delete-btn":
            selected = self.query_one("#conv-list", ListView).highlighted_child
            if selected and hasattr(selected.children[0], 'conversation_id'):
                self.dismiss(('delete', selected.children[0].conversation_id))
        else:
            self.dismiss(None)


class ChatPanel(Container):
    """Enhanced chatbot interface"""

    BINDINGS = [
        Binding("ctrl+l", "clear_chat", "Clear Chat", show=True),
        Binding("ctrl+y", "copy_last_response", "Copy Last", show=True),
        Binding("ctrl+n", "new_conversation", "New Chat", show=True),
        Binding("ctrl+o", "open_conversation", "Open Chat", show=True),
        Binding("ctrl+e", "export_conversation", "Export", show=True),
    ]

    def __init__(self, chat_manager: ChatManager, **kwargs):
        super().__init__(**kwargs)
        self.chat_manager = chat_manager
        self.conv_manager = ConversationManager()
        self.current_conversation_id = None
        self.ai_response_widget = None
        self.message_count = 0
        self.last_ai_response_text = ""

    def compose(self) -> ComposeResult:
        # Status bar showing current conversation
        yield Static("[dim]New Conversation[/]", id="conversation-status")

        # Messages container
        yield VerticalScroll(id="chat-messages-area")

        # Input area at bottom
        with Horizontal(id="chat-input-area"):
            yield TextArea(
                id="chat-input",
                show_line_numbers=False
            )
            yield Button("Send", variant="primary", id="send-btn")
            yield Button("Tools", variant="default", id="tools-btn")

    def on_mount(self) -> None:
        """Initialize chat"""
        # Initialize tables
        init_conversation_tables()

        # Create initial conversation
        self.action_new_conversation()

        # Welcome messages
        self.add_message("system", "👋 Hello! I'm DevLog Enhanced.")
        self.add_message("system", "💡 Try: '/help' for commands, or just ask naturally!")
        self.add_message("system", "🔧 Available: search, analyze, review, stats, and more")

        # Focus input
        self.call_after_refresh(self.focus_input)

    def focus_input(self) -> None:
        """Focus the input field"""
        try:
            self.query_one("#chat-input", TextArea).focus()
        except Exception as e:
            logger.error(f"Failed to focus input: {e}")

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the chat display"""
        try:
            messages_area = self.query_one("#chat-messages-area", VerticalScroll)
            self.message_count += 1

            if role == "user":
                # User message
                msg = Label(
                    f"[bold blue]You:[/bold blue] {content}",
                    classes="chat-message user-message",
                    markup=True
                )
                messages_area.mount(msg)
                messages_area.scroll_end(animate=False)
                self.ai_response_widget = None

                # Save to DB
                if self.current_conversation_id:
                    self.conv_manager.add_message(
                        self.current_conversation_id,
                        "user",
                        content
                    )

            elif role == "system":
                # System message
                msg = Label(
                    f"[bold green]System:[/bold green] {content}",
                    classes="chat-message system-message",
                    markup=True
                )
                messages_area.mount(msg)
                messages_area.scroll_end(animate=False)

            elif role == "ai_start":
                # Start a new AI response widget
                self.ai_response_widget = Label(
                    "[bold magenta]DevLog:[/bold magenta] ",
                    classes="chat-message ai-message",
                    markup=True
                )
                self.ai_response_widget._content_buffer = "[bold magenta]DevLog:[/bold magenta] "
                self.last_ai_response_text = ""

                messages_area.mount(self.ai_response_widget)
                messages_area.scroll_end(animate=False)

            elif role == "ai_stream":
                # Append to existing AI response
                if self.ai_response_widget:
                    self.ai_response_widget._content_buffer += content
                    self.last_ai_response_text += content
                    self.ai_response_widget.update(self.ai_response_widget._content_buffer)
                    messages_area.scroll_end(animate=False)

        except Exception as e:
            logger.error(f"Error adding message: {e}")

    async def on_key(self, event: Key) -> None:
        """Handle key events for submission"""
        if event.key == "enter":
            if not event.shift:
                # Enter alone: submit message
                if self.query_one("#chat-input", TextArea).has_focus:
                    event.prevent_default()
                    event.stop()
                    await self.submit_message()
            else:
                # Shift+Enter: let TextArea handle it (insert newline)
                pass

    async def submit_message(self) -> None:
        """Submit message from TextArea"""
        input_widget = self.query_one("#chat-input", TextArea)
        message = input_widget.text.strip()
        if message:
            input_widget.text = ""
            await self.send_message(message)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks"""
        try:
            if event.button.id == "send-btn":
                await self.submit_message()
            elif event.button.id == "tools-btn":
                self.add_message("system", "Available tools: /help, /search, /analyze, /review, /stats")
        except Exception as e:
            logger.error(f"Error in on_button_pressed: {e}")
            self.app.notify(f"Error: {e}", severity="error")

    def action_copy_last_response(self) -> None:
        """Copy the last AI response to clipboard"""
        if self.last_ai_response_text:
            try:
                pyperclip.copy(self.last_ai_response_text)
                self.app.notify("📋 Copied last response!", severity="information")
            except Exception as e:
                self.app.notify(f"Failed to copy: {e}", severity="error")
        else:
            self.app.notify("No response to copy yet.", severity="warning")

    def action_new_conversation(self) -> None:
        """Start new conversation"""
        # Auto-title old conversation if exists
        if self.current_conversation_id:
            self.conv_manager.auto_title_conversation(self.current_conversation_id)

        # Create new
        self.current_conversation_id = self.conv_manager.create_conversation()
        self.chat_manager.current_conversation_id = self.current_conversation_id

        # Update status
        self.query_one("#conversation-status", Static).update(
            f"[dim]Conversation #{self.current_conversation_id}[/]"
        )

        # Clear chat display
        messages_area = self.query_one("#chat-messages-area", VerticalScroll)
        messages_area.remove_children()
        self.message_count = 0

        # Clear history
        self.chat_manager.clear_history()

        self.app.notify("New conversation started", severity="information")

    def action_open_conversation(self) -> None:
        """Open existing conversation"""
        def handle_result(result):
            if result:
                action, conv_id = result
                if action == 'load':
                    self._load_conversation(conv_id)
                elif action == 'delete':
                    self.conv_manager.delete_conversation(conv_id)
                    self.app.notify("Conversation deleted", severity="information")

        self.app.push_screen(ConversationListModal(), handle_result)

    def _load_conversation(self, conversation_id: int):
        """Load conversation from DB"""
        messages = self.conv_manager.get_messages(conversation_id)

        # Update chat manager state
        self.chat_manager.clear_history()
        self.chat_manager.repopulate_history(messages)

        # Clear current UI
        messages_area = self.query_one("#chat-messages-area", VerticalScroll)
        messages_area.remove_children()
        self.message_count = 0

        # Load messages
        for msg in messages:
            role = msg['role']
            content = msg['content']

            if role == "user":
                self.add_message("user", content)
            elif role == "assistant":
                self.add_message("ai_start", "")
                self.add_message("ai_stream", content)
            elif role == "tool":
                self.add_message("system", f"[Tool: {msg['tool_name']}]")

        self.current_conversation_id = conversation_id
        self.chat_manager.current_conversation_id = conversation_id

        # Update status
        conv = self.conv_manager.get_conversation(conversation_id)
        if conv:
            self.query_one("#conversation-status", Static).update(
                f"[dim]{conv['title']}[/]"
            )

        self.app.notify(f"Loaded conversation #{conversation_id}", severity="information")

    def action_export_conversation(self) -> None:
        """Export current conversation"""
        if not self.current_conversation_id:
            self.app.notify("No conversation to export", severity="warning")
            return

        markdown = self.conv_manager.export_conversation(
            self.current_conversation_id,
            format='markdown'
        )

        # Save to file
        from datetime import datetime
        filename = f"devlog_conversation_{self.current_conversation_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        with open(filename, 'w') as f:
            f.write(markdown)

        self.app.notify(f"Exported to {filename}", severity="information")

    async def send_message(self, message: str) -> None:
        """Send a message and get AI response"""
        # Add user message
        self.add_message("user", message)

        # Start AI response
        self.add_message("ai_start", "")

        # Get response in background
        self.get_ai_response(message)

    @work(exclusive=True)
    async def get_ai_response(self, message: str) -> None:
        """Get AI response as a background task"""
        try:
            response_gen = self.chat_manager.send_message(message)
            async for chunk in response_gen:
                self.add_message("ai_stream", chunk)

            if self.current_conversation_id:
                self.conv_manager.add_message(
                    self.current_conversation_id,
                    "assistant",
                    self.last_ai_response_text,
                )
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            self.add_message("system", f"❌ {error_msg}")
        finally:
            self.focus_input()

    def action_clear_chat(self) -> None:
        """Clear chat history"""
        self.action_new_conversation()


class DevLogChat(App):
    """DevLog Chat Application"""

    CSS = """
    Screen {
        background: $surface;
    }

    #conversation-status {
        dock: top;
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text-muted;
    }

    ChatPanel {
        layout: vertical;
        height: 100%;
        width: 100%;
    }

    #chat-messages-area {
        height: 1fr;
        width: 100%;
        background: $surface;
        border: solid $primary;
        padding: 1;
    }

    .chat-message {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        padding: 0 1;
    }

    .user-message {
        background: $boost;
        color: $text;
    }

    .ai-message {
        background: $panel;
        color: $text;
    }

    .system-message {
        background: $surface;
        color: $text-muted;
    }

    #chat-input-area {
        height: auto;
        min-height: 3;
        width: 100%;
        padding: 1 0;
        background: $surface;
        dock: bottom;
    }

    #chat-input {
        width: 1fr;
        height: 3;
        background: $boost;
        border: tall $primary;
        color: $text;
    }

    #send-btn, #tools-btn {
        width: auto;
        min-width: 10;
        margin-left: 1;
        height: 3;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield ChatPanel(chat_manager=ChatManager())
        yield Footer()

    def on_mount(self) -> None:
        self.title = "DevLog Chat"
        if not test_connection():
            self.notify("⚠️ Ollama not running - AI features limited", severity="warning")


def main():
    app = DevLogChat()
    app.run()


if __name__ == "__main__":
    main()
