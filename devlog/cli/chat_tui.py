"""
DevLog Chat TUI - Standalone Chat Interface
Direct conversation with the AI, separated from the main dashboard.
"""
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Footer, Static, Input, Button, Label
from textual.binding import Binding
from textual import work
from devlog.analysis.chat_manager import ChatManager
from devlog.analysis.llm import test_connection
import logging

# Setup logging
logging.basicConfig(
    filename='devlog_chat_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ChatPanel(Container):
    """Chatbot interface"""

    BINDINGS = [
        Binding("ctrl+l", "clear_chat", "Clear Chat", show=True),
    ]

    def __init__(self, chat_manager: ChatManager, **kwargs):
        super().__init__(**kwargs)
        self.chat_manager = chat_manager
        self.ai_response_widget = None
        self.message_count = 0

    def compose(self) -> ComposeResult:
        """Build the chat UI"""
        # Messages container
        yield VerticalScroll(id="chat-messages-area")
        
        # Input area at bottom
        with Horizontal(id="chat-input-area"):
            yield Input(
                placeholder="Ask DevLog a question... (Press Enter to send)",
                id="chat-input"
            )
            yield Button("Send", variant="primary", id="send-btn")
            yield Button("Clear", variant="default", id="clear-btn")

    def on_mount(self) -> None:
        """Initialize chat"""
        self.add_message("system", "👋 Hello! I'm DevLog. How can I help you today?")
        self.add_message("system", "💡 Tip: I can search your commits and the web for you!")
        # Focus input after mount
        self.call_after_refresh(self.focus_input)

    def focus_input(self) -> None:
        """Focus the input field"""
        try:
            self.query_one("#chat-input", Input).focus()
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
                # Initialize a buffer for this widget
                self.ai_response_widget._content_buffer = "[bold magenta]DevLog:[/bold magenta] "
                messages_area.mount(self.ai_response_widget)
                messages_area.scroll_end(animate=False)
                
            elif role == "ai_stream":
                # Append to existing AI response
                if self.ai_response_widget:
                    self.ai_response_widget._content_buffer += content
                    self.ai_response_widget.update(self.ai_response_widget._content_buffer)
                    messages_area.scroll_end(animate=False)
        except Exception as e:
            logger.error(f"Error adding message: {e}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input"""
        if event.input.id == "chat-input":
            message = event.input.value.strip()
            if message:
                event.input.value = ""
                await self.send_message(message)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks"""
        if event.button.id == "send-btn":
            input_widget = self.query_one("#chat-input", Input)
            message = input_widget.value.strip()
            if message:
                input_widget.value = ""
                await self.send_message(message)
                
        elif event.button.id == "clear-btn":
            self.action_clear_chat()

    async def send_message(self, message: str) -> None:
        """Send a message and get AI response"""
        # Add user message
        self.add_message("user", message)
        
        # Start AI response
        self.add_message("ai_start", "")
        
        # Get response in background
        self.get_ai_response(message)

    @work(exclusive=True, thread=True)
    def get_ai_response(self, message: str) -> None:
        """Get AI response in background thread"""
        try:
            import asyncio
            
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Get the async generator
            response_gen = self.chat_manager.send_message(message)
            
            # Consume the generator
            async def consume():
                async for chunk in response_gen:
                    # Call add_message from the main thread
                    # Use self.app.call_from_thread because we are inside a widget
                    self.app.call_from_thread(self.add_message, "ai_stream", chunk)
            
            loop.run_until_complete(consume())
            loop.close()
            
            # Re-focus input when done
            self.app.call_from_thread(self.focus_input)
            
        except Exception as e:
            error_msg = f"Error: {str(e)}"
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


class DevLogChat(App):
    """DevLog Standalone Chat Application"""

    CSS = """
    Screen {
        background: $surface;
    }

    /* Chat Panel Styling */
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
        width: 100%;
        padding: 1;
        background: $surface;
        dock: bottom;
    }

    #chat-input {
        width: 1fr;
        background: $boost;
        border: tall $primary;
        color: $text;
    }

    #send-btn, #clear-btn {
        width: auto;
        min-width: 10;
        margin-left: 1;
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
            self.notify("⚠️ Ollama not running - AI features disabled", severity="warning")

def main():
    app = DevLogChat()
    app.run()

if __name__ == "__main__":
    main()
