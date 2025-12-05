import click
import sqlite3
import os
from rich import print
from datetime import datetime

DB_DIR = os.path.expanduser("~/.devlog")
DB_PATH = os.path.join(DB_DIR, "devlog.db")

def init_db():
    """Initialize the database"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
            tag TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

@click.group()
def cli():
    """DevLog CLI"""
    init_db()
    print("[bold green]DevLog CLI running...[/]")


@cli.command()
@click.option('--tag', default=None, help="Filter by tag")
@click.argument("message")
def add(message):
    """Add a new log message"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO notes (message, created_at, tag)
        VALUES (?, ?, ?);
    """, (message, datetime.now().isoformat(), tag))
    conn.commit()
    conn.close()

    print(f"[bold green]Added log message:[/] {message}")


if __name__ == "__main__":
    cli()

