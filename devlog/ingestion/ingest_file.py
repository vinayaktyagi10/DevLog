import os
from datetime import datetime
import sqlite3

from devlog.ingestion.normalize import normalize_text
from devlog.ingestion.title_extractor import extract_title
from devlog.ingestion.pdf import extract_pdf_text
from devlog.ingestion.plaintext import extract_plaintext
from devlog.ingestion.markdown import extract_markdown
from devlog.ingestion.docx import extract_docx
from devlog.ingestion.pptx import extract_pptx

from devlog.paths import DB_PATH, DB_DIR
def ingest_file(path, purpose="study", semester="III", subject="Unknown"):
    ext = os.path.splitext(path)[1].lower()

    if ext == ".pdf":
        raw = extract_pdf_text(path)
    elif ext == ".txt" or ext == ".log":
        raw = extract_plaintext(path)
    elif ext == ".md":
        raw = extract_markdown(path)
    elif ext == ".docx":
        raw = extract_docx(path)
    elif ext == ".pptx":
        raw = extract_pptx(path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    raw = normalize_text(raw)
    title = extract_title(raw)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO entries
        (raw_text, parent_id, subpart, summary, status, created_at, source, purpose, file_path, file_type, subject, semester)
        VALUES (?, NULL, NULL, NULL, 'raw', ?, 'file-import', ?, ?, ?, ?, ?)
        """, (raw, datetime.now().isoformat(), purpose, path, ext, subject, semester))

    inserted_id = c.lastrowid
    conn.commit()
    conn.close()

    return 1, [inserted_id]

