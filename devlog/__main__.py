import click
import sqlite3
import os
from rich import print
from rich.table import Table
from rich.console import Console
from datetime import datetime
from devlog.llm import call_llm

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
            raw_text TEXT NOT NULL,
            summary TEXT NULL,
            status TEXT NOT NULL default "raw",
            created_at TEXT NOT NULL
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
@click.argument("message")
def add(message):
    """Add a new log message"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO notes (raw_text, created_at)
        VALUES (?, ?)
    """, (message, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    print(f"[bold green]Added log message:[/] {message}")

@cli.command()
def process():
    """Process the log messages"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        select id, raw_text from notes where status = "raw"
    """)
    raw_logs = c.fetchall()
    conn.close()


    count = 0
    for note_id, raw_text in raw_logs:
        summary = call_llm(raw_text)
        conn_summary = sqlite3.connect(DB_PATH)
        c_summary = conn_summary.cursor()
        c_summary.execute("""
            UPDATE notes SET summary = ?, status = "summarized" WHERE id = ?
        """, (summary, note_id))
        conn_summary.commit()
        conn_summary.close()
        count += 1

    print(f"[bold green]Processed {count} notes.[/]")
@cli.command()
def list():
    """List the log messages"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        select id, raw_text, summary, status from notes
    """)
    logs = c.fetchall()
    conn.close()
    table = Table(title="Summarized Log Messages")
    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("Raw Text", style="magenta")
    table.add_column("Summary", style="green")
    table.add_column("Status", style="yellow")
    for log in logs:
        table.add_row(str(log[0]), log[1], log[2] or "-", log[3])
    console = Console()
    console.print(table)



if __name__ == "__main__":
    cli()

