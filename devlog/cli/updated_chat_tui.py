"""
Fixed Enhanced Chat TUI - Working with existing chat manager
"""
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, Static, TextArea, Button, Label
from textual.binding import Binding
from textual import work
from textual.events import Key
import logging
import pyperclip
import asyncio

from devlog.analysis.chat_manager import ChatManager
from devlog.analysis.llm import test_connection

# Setup logging
logging.basicConfig(
    filename='devlog_chat_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ChatPanel(Container):
    """Enhanced chatbot interface with tool support"""

    BINDINGS = [
        Binding("ctrl+l", "clear_chat", "Clear Chat", show=True),
        Binding("ctrl+y", "copy_last_response", "Copy Last", show=True),
    ]

    def __init__(self, chat_manager: ChatManager, **kwargs):
        super().__init__(**kwargs)
        self.chat_manager = chat_manager
        self.ai_response_widget = None
        self.message_count = 0
        self.last_ai_response_text = ""

    def compose(self) -> ComposeResult:
        """Build the chat UI"""
        # Status bar
        yield Static("[dim]Chat Session Active[/]", id="chat-status")

        # Messages container
        yield VerticalScroll(id="chat-messages-area")

        # Input area at bottom
        with Horizontal(id="chat-input-area"):
            yield TextArea(
                id="chat-input",
                show_line_numbers=False
            )
            yield Button("Send", variant="primary", id="send-btn")
            yield Button("Clear", variant="default", id="clear-btn")

    def on_mount(self) -> None:
        """Initialize chat"""
        self.add_message("system", "👋 Hello! I'm DevLog Enhanced.")
        self.add_message("system", "💡 I can search your commits, analyze code, and help with reviews.")
        self.add_message("system", "🔍 Try asking: 'Show me my recent commits' or 'Search for authentication code'")
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
                msg = Label(
                    f"[bold blue]You:[/bold blue] {content}",
                    classes="chat-message user-message",
                    markup=True
                )
                messages_area.mount(msg)
                messages_area.scroll_end(animate=False)
                self.ai_response_widget = None

            elif role == "system":
                msg = Label(
                    f"[bold green]System:[/bold green] {content}",
                    classes="chat-message system-message",
                    markup=True
                )
                messages_area.mount(msg)
                messages_area.scroll_end(animate=False)

            elif role == "ai_start":
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
                if self.ai_response_widget:
                    # Escape any markup characters in the streamed content
                    escaped_content = content.replace("[", "\\[")
                    self.ai_response_widget._content_buffer += escaped_content
                    self.last_ai_response_text += content  # Store unescaped for copying
                    self.ai_response_widget.update(self.ai_response_widget._content_buffer)
                    messages_area.scroll_end(animate=False)

        except Exception as e:
            logger.error(f"Error adding message: {e}")

    async def on_key(self, event: Key) -> None:
        """Handle key events for submission"""
        try:
            if event.key == "enter":
                if not event.shift:
                    if self.query_one("#chat-input", TextArea).has_focus:
                        event.prevent_default()
                        event.stop()
                        await self.submit_message()
                else:
                    # Shift+Enter: let it fall through to insert newline
                    pass
        except Exception as e:
            logger.error(f"Error in on_key: {e}")
            self.app.notify(f"Error: {e}", severity="error")

    async def submit_message(self) -> None:
        """Submit message from TextArea"""
        input_widget = self.query_one("#chat-input", TextArea)
        message = input_widget.text.strip()
        if message:
            input_widget.text = ""
            await self.send_message(message)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks"""
        if event.button.id == "send-btn":
            await self.submit_message()
        elif event.button.id == "clear-btn":
            self.action_clear_chat()

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

    async def send_message(self, message: str) -> None:
        """Send a message and get AI response"""
        self.add_message("user", message)
        self.add_message("ai_start", "")
        self.get_ai_response(message)

    @work(exclusive=True, thread=True)
    def get_ai_response(self, message: str) -> None:
        """Get AI response in background thread"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            response_gen = self.chat_manager.send_message(message)

            async def consume():
                async for chunk in response_gen:
                    self.app.call_from_thread(self.add_message, "ai_stream", chunk)

            loop.run_until_complete(consume())
            loop.close()

            self.app.call_from_thread(self.focus_input)

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error(f"Chat error: {e}", exc_info=True)
            self.app.call_from_thread(self.add_message, "system", f"❌ {error_msg}")
            self.app.call_from_thread(self.focus_input)

    def action_clear_chat(self) -> None:
        """Clear chat history"""
        self.chat_manager.clear_history()
        messages_area = self.query_one("#chat-messages-area", VerticalScroll)
        messages_area.remove_children()
        self.message_count = 0
        self.add_message("system", "Chat cleared. How can I help you?")
        self.focus_input()


class EnhancedDevLogChat(App):
    """Enhanced DevLog Chat Application"""

    CSS = """
    Screen {
        background: $surface;
    }

    #chat-status {
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

    #send-btn, #clear-btn {
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
        self.title = "DevLog Enhanced Chat"
        if not test_connection():
            self.notify("⚠️ Ollama not running - AI features limited", severity="warning")


def main():
    app = EnhancedDevLogChat()
    app.run()


if __name__ == "__main__":
    main()
