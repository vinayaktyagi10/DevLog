import os
import re
from datetime import datetime
import sqlite3

from devlog.ingestion.normalize import normalize_text
from devlog.ingestion.title_extractor import extract_title
from devlog.ingestion.pdf import extract_pdf_text
from devlog.ingestion.plaintext import extract_plaintext
from devlog.ingestion.markdown import extract_markdown
from devlog.ingestion.docx import extract_docx
from devlog.ingestion.pptx import extract_pptx
from devlog.ingestion.chunk_exam import chunk_exam

from devlog.paths import DB_PATH, DB_DIR


def detect_exam_paper(text, filename=""):
    """
    Detect if the document is an exam paper based on content and filename.

    Args:
        text: normalized document text
        filename: filename of the document

    Returns:
        bool: True if document appears to be an exam paper
    """
    # Check filename patterns
    filename_lower = filename.lower()
    filename_patterns = [
        r'exam', r'test', r'quiz', r'mid\s*term', r'final',
        r'question\s*paper', r'qp', r'assessment'
    ]

    for pattern in filename_patterns:
        if re.search(pattern, filename_lower):
            return True

    # Check content patterns (look in first 500 chars)
    content_check = text[:500].lower()

    # Strong indicators
    strong_indicators = [
        r'max(?:imum)?\s*marks?\s*[:\-]?\s*\d+',
        r'time\s*[:\-]\s*\d+\s*(?:hours?|hrs?|minutes?|mins?)',
        r'total\s*marks?\s*[:\-]?\s*\d+',
        r'q(?:\.|uestion)?\s*no\.?\s*\d+',
        r'answer\s+(?:all|any|the\s+following)',
        r'mid\s*term|final\s*exam|semester\s*exam',
    ]

    strong_matches = sum(1 for pattern in strong_indicators if re.search(pattern, content_check))

    # If we have 2+ strong indicators, it's likely an exam
    if strong_matches >= 2:
        return True

    # Check for multiple numbered questions in early content
    lines = text.splitlines()[:30]  # Check first 30 lines
    question_pattern = re.compile(r'^(?:Q(?:\.|uestion)?\s*No\.?\s*)?\d{1,2}[\.\)\:\-\s]', re.I)
    question_count = sum(1 for line in lines if question_pattern.match(line.strip()))

    # If we have 3+ questions in first 30 lines, likely an exam
    if question_count >= 3:
        return True

    return False


def ingest_file(path, purpose="study", semester="III", subject="Unknown", force_exam=False):
    """
    Ingest a file into the database.

    Args:
        path: path to the file
        purpose: purpose of the file (study/exam/dev)
        semester: semester number
        subject: subject name
        force_exam: if True, force exam paper chunking

    Returns:
        tuple: (count, inserted_ids)
    """
    ext = os.path.splitext(path)[1].lower()
    filename = os.path.basename(path)

    # Extract raw text based on file type
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

    # Normalize text
    raw = normalize_text(raw)

    # Detect if this is an exam paper
    is_exam = force_exam or detect_exam_paper(raw, filename)

    if is_exam:
        print(f"[INFO] Detected exam paper format - using chunking")

        # Prepare metadata for chunking
        meta = {
            "file_path": path,
            "file_type": ext,
            "subject": subject,
            "semester": semester,
            "purpose": "exam"  # Override purpose for exam papers
        }

        # Use exam chunking
        count, ids = chunk_exam(raw, meta, verbose=True, keep_headers=False)
        return count, ids

    else:
        # Regular single-document ingestion
        print(f"[INFO] Regular document format - single entry")
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
