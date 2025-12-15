"""
Conversation Persistence - Database schema and operations
"""

import sqlite3
import json
from typing import List, Dict, Optional, Any
from datetime import datetime
from devlog.paths import DB_PATH


def init_conversation_tables():
    """Initialize conversation tables"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Conversations table
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_message_at TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            tags TEXT,  -- JSON array
            archived BOOLEAN DEFAULT 0,
            UNIQUE(title, created_at)
        )
    """)

    # Messages table
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,  -- user/assistant/tool/system
            content TEXT NOT NULL,
            tool_name TEXT,
            tool_result TEXT,  -- JSON
            timestamp TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE
        )
    """)

    # Create indices
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_conversation
        ON chat_messages(conversation_id)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_timestamp
        ON chat_messages(timestamp)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_last_message
        ON chat_conversations(last_message_at)
    """)

    conn.commit()
    conn.close()


class ConversationManager:
    """Manage conversation persistence"""

    def __init__(self):
        init_conversation_tables()

    def create_conversation(self, title: str = None) -> int:
        """
        Create new conversation

        Returns:
            Conversation ID
        """
        if not title:
            title = f"Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        now = datetime.now().isoformat()

        c.execute("""
            INSERT INTO chat_conversations (title, created_at, last_message_at)
            VALUES (?, ?, ?)
        """, (title, now, now))

        conversation_id = c.lastrowid
        conn.commit()
        conn.close()

        return conversation_id

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        tool_name: Optional[str] = None,
        tool_result: Optional[Dict] = None
    ) -> int:
        """
        Add message to conversation

        Returns:
            Message ID
        """
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        now = datetime.now().isoformat()

        tool_result_json = json.dumps(tool_result) if tool_result else None

        c.execute("""
            INSERT INTO chat_messages
            (conversation_id, role, content, tool_name, tool_result, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (conversation_id, role, content, tool_name, tool_result_json, now))

        message_id = c.lastrowid

        # Update conversation
        c.execute("""
            UPDATE chat_conversations
            SET last_message_at = ?,
                message_count = message_count + 1
            WHERE id = ?
        """, (now, conversation_id))

        conn.commit()
        conn.close()

        return message_id

    def get_conversation(self, conversation_id: int) -> Optional[Dict]:
        """Get conversation details"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT * FROM chat_conversations WHERE id = ?
        """, (conversation_id,))

        row = c.fetchone()
        conn.close()

        if not row:
            return None

        return dict(row)

    def get_messages(self, conversation_id: int) -> List[Dict]:
        """Get all messages in a conversation"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT * FROM chat_messages
            WHERE conversation_id = ?
            ORDER BY timestamp ASC
        """, (conversation_id,))

        messages = [dict(row) for row in c.fetchall()]
        conn.close()

        # Parse tool_result JSON
        for msg in messages:
            if msg.get('tool_result'):
                try:
                    msg['tool_result'] = json.loads(msg['tool_result'])
                except:
                    pass

        return messages

    def list_conversations(
        self,
        limit: int = 50,
        archived: bool = False
    ) -> List[Dict]:
        """List recent conversations"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            SELECT * FROM chat_conversations
            WHERE archived = ?
            ORDER BY last_message_at DESC
            LIMIT ?
        """, (archived, limit))

        conversations = [dict(row) for row in c.fetchall()]
        conn.close()

        return conversations

    def update_title(self, conversation_id: int, title: str):
        """Update conversation title"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("""
            UPDATE chat_conversations
            SET title = ?
            WHERE id = ?
        """, (title, conversation_id))

        conn.commit()
        conn.close()

    def add_tags(self, conversation_id: int, tags: List[str]):
        """Add tags to conversation"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Get existing tags
        c.execute("SELECT tags FROM chat_conversations WHERE id = ?", (conversation_id,))
        row = c.fetchone()

        existing_tags = []
        if row and row[0]:
            try:
                existing_tags = json.loads(row[0])
            except:
                pass

        # Merge tags
        all_tags = list(set(existing_tags + tags))

        c.execute("""
            UPDATE chat_conversations
            SET tags = ?
            WHERE id = ?
        """, (json.dumps(all_tags), conversation_id))

        conn.commit()
        conn.close()

    def archive_conversation(self, conversation_id: int):
        """Archive conversation"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("""
            UPDATE chat_conversations
            SET archived = 1
            WHERE id = ?
        """, (conversation_id,))

        conn.commit()
        conn.close()

    def delete_conversation(self, conversation_id: int):
        """Delete conversation (cascades to messages)"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("DELETE FROM chat_conversations WHERE id = ?", (conversation_id,))

        conn.commit()
        conn.close()

    def search_conversations(self, query: str, limit: int = 20) -> List[Dict]:
        """Search conversations by title or content"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        search_term = f"%{query}%"

        c.execute("""
            SELECT DISTINCT c.*
            FROM chat_conversations c
            LEFT JOIN chat_messages m ON c.id = m.conversation_id
            WHERE c.title LIKE ? OR m.content LIKE ?
            ORDER BY c.last_message_at DESC
            LIMIT ?
        """, (search_term, search_term, limit))

        conversations = [dict(row) for row in c.fetchall()]
        conn.close()

        return conversations

    def get_conversation_summary(self, conversation_id: int) -> Dict[str, Any]:
        """Get conversation summary statistics"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Message counts by role
        c.execute("""
            SELECT role, COUNT(*) as count
            FROM chat_messages
            WHERE conversation_id = ?
            GROUP BY role
        """, (conversation_id,))

        role_counts = {row[0]: row[1] for row in c.fetchall()}

        # Tool usage
        c.execute("""
            SELECT tool_name, COUNT(*) as count
            FROM chat_messages
            WHERE conversation_id = ? AND tool_name IS NOT NULL
            GROUP BY tool_name
        """, (conversation_id,))

        tool_counts = {row[0]: row[1] for row in c.fetchall()}

        conn.close()

        return {
            'role_counts': role_counts,
            'tool_counts': tool_counts,
            'total_messages': sum(role_counts.values())
        }

    def export_conversation(
        self,
        conversation_id: int,
        format: str = 'markdown'
    ) -> str:
        """
        Export conversation to markdown or JSON

        Args:
            conversation_id: Conversation ID
            format: 'markdown' or 'json'

        Returns:
            Formatted conversation
        """
        conversation = self.get_conversation(conversation_id)
        messages = self.get_messages(conversation_id)

        if not conversation:
            return "Conversation not found"

        if format == 'json':
            return json.dumps({
                'conversation': conversation,
                'messages': messages
            }, indent=2)

        # Markdown format
        lines = [
            f"# {conversation['title']}",
            f"",
            f"**Created:** {conversation['created_at']}",
            f"**Last Updated:** {conversation['last_message_at']}",
            f"**Messages:** {conversation['message_count']}",
            f"",
            "---",
            ""
        ]

        for msg in messages:
            role = msg['role']
            content = msg['content']
            timestamp = msg['timestamp'].split('T')[1].split('.')[0]  # Just time

            if role == 'user':
                lines.append(f"### 👤 User [{timestamp}]")
            elif role == 'assistant':
                lines.append(f"### 🤖 Assistant [{timestamp}]")
            elif role == 'tool':
                lines.append(f"### 🔧 Tool: {msg['tool_name']} [{timestamp}]")
            else:
                lines.append(f"### {role.title()} [{timestamp}]")

            lines.append("")
            lines.append(content)
            lines.append("")

            if msg.get('tool_result'):
                lines.append("**Tool Result:**")
                lines.append("```json")
                lines.append(json.dumps(msg['tool_result'], indent=2))
                lines.append("```")
                lines.append("")

        return "\n".join(lines)

    def auto_title_conversation(self, conversation_id: int):
        """
        Auto-generate title from first few messages
        """
        messages = self.get_messages(conversation_id)

        if not messages:
            return

        # Use first user message as title
        first_user_msg = next((m for m in messages if m['role'] == 'user'), None)

        if first_user_msg:
            # Take first 50 chars
            title = first_user_msg['content'][:50]

            # Clean up
            title = title.replace('\n', ' ').strip()

            if len(first_user_msg['content']) > 50:
                title += "..."

            self.update_title(conversation_id, title)


# ==================== UTILITY FUNCTIONS ====================

def get_conversation_manager() -> ConversationManager:
    """Get singleton conversation manager"""
    return ConversationManager()


def create_new_conversation(title: str = None) -> int:
    """Quick function to create conversation"""
    manager = get_conversation_manager()
    return manager.create_conversation(title)


def save_message(
    conversation_id: int,
    role: str,
    content: str,
    tool_name: Optional[str] = None,
    tool_result: Optional[Dict] = None
) -> int:
    """Quick function to save message"""
    manager = get_conversation_manager()
    return manager.add_message(conversation_id, role, content, tool_name, tool_result)


def load_conversation(conversation_id: int) -> Dict[str, Any]:
    """Quick function to load full conversation"""
    manager = get_conversation_manager()

    conversation = manager.get_conversation(conversation_id)
    if not conversation:
        return {}

    messages = manager.get_messages(conversation_id)
    summary = manager.get_conversation_summary(conversation_id)

    return {
        'conversation': conversation,
        'messages': messages,
        'summary': summary
    }
