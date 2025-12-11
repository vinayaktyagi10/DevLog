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
    """DevLog CLI - A tool for managing study materials and dev logs"""
    init_db()
    print("[bold green]DevLog CLI running...[/]")


@cli.command()
@click.argument("message")
@click.option("--subject", "-s", default="General", help="Subject name")
@click.option("--semester", "-sem", default="IV", help="Semester")
@click.option("--purpose", "-p", default="study", help="Purpose: study/exam/dev")
@click.option("--force-exam", "-e", is_flag=True, help="Force exam paper chunking")
def add(message, subject, semester, purpose, force_exam):
    """Add a new log message or import a file"""

    # Check if message is a file
    if os.path.exists(message) and os.path.isfile(message):
        file_extension = os.path.splitext(message)[1].lower()
        if file_extension in [".pdf", ".docx", ".pptx", ".md", ".txt", ".log"]:
            count, ids = ingest_file(
                message,
                purpose=purpose,
                semester=semester,
                subject=subject,
                force_exam=force_exam
            )
            print(f"[bold green]✓ Imported {count} chunks from {message}[/]")
            print(f"[bold cyan]Entry IDs: {ids}[/]")
            print("[bold yellow]→ Run 'devlog process' to summarize the entries.[/]")
            return
        else:
            print(f"[bold red]Error:[/] Unsupported file type: {file_extension}")
            return
    elif os.path.exists(message) and os.path.isdir(message):
        print("[bold red]Error:[/] Cannot add a directory as a log message.")
        return

    # Add as manual text entry
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        INSERT INTO entries
        (raw_text, parent_id, subpart, summary, status, created_at, source, purpose, file_path, file_type, subject, semester)
        VALUES (?, NULL, NULL, NULL, 'raw', ?, 'manual', ?, NULL, NULL, ?, ?)
    """, (message, datetime.now().isoformat(), purpose, subject, semester))

    conn.commit()
    conn.close()
    print(f"[bold green]✓ Added log message:[/] {message}")


@cli.command()
@click.option("--limit", "-l", default=None, type=int, help="Limit number of entries to process")
def process(limit):
    """Process raw log messages and generate summaries"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    query = "SELECT id, raw_text FROM entries WHERE status = 'raw'"
    if limit:
        query += f" LIMIT {limit}"

    c.execute(query)
    raw_logs = c.fetchall()
    conn.close()

    if not raw_logs:
        print("[bold yellow]No raw entries to process.[/]")
        return

    print(f"[bold cyan]Processing {len(raw_logs)} entries...[/]")
    count = 0

    for note_id, raw_text in raw_logs:
        print(f"[dim]Processing entry {note_id}...[/dim]", end=" ")
        summary = call_llm(raw_text)

        conn_summary = sqlite3.connect(DB_PATH)
        c_summary = conn_summary.cursor()
        c_summary.execute("""
            UPDATE entries SET summary = ?, status = "summarized" WHERE id = ?
        """, (summary, note_id))
        conn_summary.commit()
        conn_summary.close()
        count += 1
        print("[bold green]✓[/]")

    print(f"[bold green]✓ Processed {count} entries.[/]")


@cli.command()
@click.option("--status", "-s", default=None, help="Filter by status: raw/summarized")
@click.option("--subject", "-sub", default=None, help="Filter by subject")
@click.option("--purpose", "-p", default=None, help="Filter by purpose")
@click.option("--parent-only", "-po", is_flag=True, help="Show only parent questions")
def list(status, subject, purpose, parent_only):
    """List log messages and entries"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    query = "SELECT id, raw_text, summary, status, subject, purpose, parent_id, subpart FROM entries WHERE 1=1"
    params = []

    if status:
        query += " AND status = ?"
        params.append(status)

    if subject:
        query += " AND subject = ?"
        params.append(subject)

    if purpose:
        query += " AND purpose = ?"
        params.append(purpose)

    if parent_only:
        query += " AND parent_id IS NULL"

    query += " ORDER BY created_at DESC"

    c.execute(query, params)
    logs = c.fetchall()
    conn.close()

    if not logs:
        print("[bold yellow]No entries found.[/]")
        return

    table = Table(title=f"Log Entries ({len(logs)} total)")
    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("Raw Text", style="magenta", max_width=40)
    table.add_column("Summary", style="green", max_width=40)
    table.add_column("Status", style="yellow", no_wrap=True)
    table.add_column("Subject", style="blue", no_wrap=True)
    table.add_column("Type", style="white", no_wrap=True)

    for log in logs:
        entry_id, raw, summ, stat, subj, purp, parent_id, subpart = log

        # Determine entry type
        if parent_id is None and subpart is None:
            entry_type = "📄 Doc" if purp != "exam" else "📝 Parent"
        else:
            entry_type = f"  └─ {subpart}" if subpart else "  └─ Child"

        # Truncate text
        raw_preview = (raw[:37] + "...") if len(raw) > 40 else raw
        summ_preview = ((summ[:37] + "...") if len(summ) > 40 else summ) if summ else "-"

        table.add_row(
            str(entry_id),
            raw_preview,
            summ_preview,
            stat,
            subj or "-",
            entry_type
        )

    console = Console()
    console.print(table)


@cli.command()
@click.argument("entry_id", type=int)
def show(entry_id):
    """Show full details of an entry"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, raw_text, summary, status, subject, semester, purpose,
               parent_id, subpart, file_path, created_at
        FROM entries WHERE id = ?
    """, (entry_id,))

    entry = c.fetchone()

    if not entry:
        print(f"[bold red]Entry {entry_id} not found.[/]")
        conn.close()
        return

    # If this is a parent, get children
    c.execute("SELECT id, subpart, raw_text FROM entries WHERE parent_id = ? ORDER BY subpart", (entry_id,))
    children = c.fetchall()
    conn.close()

    entry_id, raw, summ, stat, subj, sem, purp, parent_id, subpart, fpath, created = entry

    console = Console()
    console.print(f"\n[bold cyan]═══ Entry {entry_id} ═══[/]")
    console.print(f"[bold]Subject:[/] {subj or 'N/A'}")
    console.print(f"[bold]Semester:[/] {sem or 'N/A'}")
    console.print(f"[bold]Purpose:[/] {purp}")
    console.print(f"[bold]Status:[/] {stat}")
    console.print(f"[bold]Created:[/] {created}")

    if parent_id:
        console.print(f"[bold]Parent ID:[/] {parent_id}")
    if subpart:
        console.print(f"[bold]Subpart:[/] {subpart}")
    if fpath:
        console.print(f"[bold]File:[/] {fpath}")

    console.print(f"\n[bold yellow]Raw Text:[/]")
    console.print(raw)

    if summ:
        console.print(f"\n[bold green]Summary:[/]")
        console.print(summ)

    if children:
        console.print(f"\n[bold magenta]Children ({len(children)}):[/]")
        for child_id, child_sub, child_raw in children:
            preview = (child_raw[:60] + "...") if len(child_raw) > 60 else child_raw
            console.print(f"  [{child_id}] ({child_sub}) {preview}")


if __name__ == "__main__":
    cli()
