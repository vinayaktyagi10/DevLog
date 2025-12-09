import click
import sqlite3
import os
from rich import print
from rich.table import Table
from rich.console import Console
from datetime import datetime
from devlog.llm import call_llm
import pymupdf
from devlog.ingestion.ingest_file import ingest_file
from devlog.paths import DB_PATH, DB_DIR


def init_db():
    """Initialize the database"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_text TEXT NOT NULL,
            parent_id INTEGER NULL,
            subpart TEXT NULL,
            summary TEXT,
            status TEXT NOT NULL default "raw",
            created_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT "user",
            purpose TEXT NOT NULL DEFAULT "dev",
            file_path TEXT,
            file_type TEXT,
            subject TEXT,
            semester TEXT
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
    if os.path.exists(message) and os.path.isfile(message):
        file_extension = os.path.splitext(message)[1].lower()
        if file_extension in [".pdf", ".docx", ".pptx", ".md", ".txt", ".log"]:
            count, ids = ingest_file(message)
            print(f"[bold green]Imported {count} chunks from {message}[/]")
            print(f"[bold green]IDs: {ids}[/]")
            print("[bold green]Run 'devlog process' to summarize the entries.[/]")
            return
        else:
            print(f"[bold red]Error:[/] Unsupported file type: {file_extension}")
            return
    elif os.path.exists(message) and os.path.isdir(message):
        print("[bold red]Error:[/] Cannot add a directory as a log message.")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        INSERT INTO entries
        (raw_text, parent_id, subpart, summary, status, created_at, source, purpose, file_path, file_type, subject, semester)
        VALUES (?, NULL, NULL, NULL, 'raw', ?, 'manual', 'dev', NULL, NULL, 'General', 'IV')
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
        select id, raw_text from entries where status = "raw"
    """)
    raw_logs = c.fetchall()
    conn.close()


    count = 0
    for note_id, raw_text in raw_logs:
        summary = call_llm(raw_text)
        conn_summary = sqlite3.connect(DB_PATH)
        c_summary = conn_summary.cursor()
        c_summary.execute("""
            UPDATE entries SET summary = ?, status = "summarized" WHERE id = ?
        """, (summary, note_id))
        conn_summary.commit()
        conn_summary.close()
        count += 1

    print(f"[bold green]Processed {count} entries.[/]")
@cli.command()
def list():
    """List the log messages"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        select id, raw_text, summary, status from entries
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

