# ---------------------------------------------------------
# devlog/ingestion/chunk_exam.py
# ---------------------------------------------------------

import re
import sqlite3
from datetime import datetime
from devlog.ingestion.normalize import normalize_text
from devlog.paths import DB_PATH

# ---------------------------- Regexes ----------------------------
# MAIN question regex: accept "Q. No. 3", "3.", "3", "3Consider", "3(a)" etc.
MAIN_Q_RE = re.compile(
    r'^(?:Q(?:\.|uestion)?\s*No\.?\s*)?(\d{1,2})'  # capture question number
    r'(?:(?:[\.\-\)\s]+)|(?=[A-Z])|$)'              # allow ., -, ), spaces or immediately uppercase
)

# SUBPART forms:
SUBPART_DIGIT_LETTER_RE = re.compile(r'^(\d{1,2})([a-z])\b', re.I)
SUBPART_PAREN_LETTER_RE = re.compile(r'^\(?([a-z])\)?[\.:\)\s\-]+', re.I)
SUBPART_WITH_PARENS_RE = re.compile(r'^(\d{1,2})\s*\(\s*([a-z])\s*\)', re.I)

# Broad ignore patterns (page headers/footers and common exam metadata)
IGNORE_PATTERNS = [
    r'^Page\s*\d+', r'^Reg\.? ?No\.?', r'Faculty of', r'Department of',
    r'Max Marks', r'Time\s*[:\-]', r'Instructions', r'Exam(?:ination)?',
    r'Mid Term', r'Odd Semester', r'Even Semester', r'Program', r'Semester',
    r'Course Code', r'Course Title'
]
IGNORE_RE = re.compile(r'|'.join(f'({p})' for p in IGNORE_PATTERNS), re.I)


def insert_entry(raw_text, parent_id, subpart, file_path, file_type,
                purpose, subject, semester, summary, status):
    """Insert an entry into the database matching your schema."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        INSERT INTO entries
        (raw_text, parent_id, subpart, summary, status, created_at,
         source, purpose, file_path, file_type, subject, semester)
        VALUES (?, ?, ?, ?, ?, ?, 'file-import', ?, ?, ?, ?, ?)
    """, (
        raw_text, parent_id, subpart, summary, status,
        datetime.now().isoformat(), purpose, file_path,
        file_type, subject, semester
    ))

    inserted_id = c.lastrowid
    conn.commit()
    conn.close()

    return inserted_id


def chunk_exam(text, meta, verbose=True, keep_headers=True, min_scan_for_question=5):
    """
    Chunk exam paper text into parent questions and child subparts.

    Args:
        text: normalized string (use normalize_text before calling)
        meta: dict with keys: file_path, file_type, subject, semester, purpose
        verbose: print debug info
        keep_headers: if False, strips the leading '3a'/'(a)' from child.raw_text
        min_scan_for_question: require at least this many lines before treating numeric phrases as questions

    Returns:
        tuple: (count, inserted_ids)
    """
    # Validate meta
    required = ["file_path", "file_type", "subject", "semester", "purpose"]
    missing = [k for k in required if k not in meta]
    if missing:
        raise ValueError(f"chunk_exam: missing meta keys: {missing}")

    lines = text.splitlines()
    n = len(lines)

    if verbose:
        print("\n=== FIRST 50 LINES PREVIEW ===")
        for i, L in enumerate(lines[:50]):
            print(f"{i:03d}: {L}")
        print("=== END PREVIEW ===\n")

    # Helper functions
    def is_ignored(line):
        return bool(IGNORE_RE.search(line.strip()))

    def match_main(line):
        s = line.strip()
        if is_ignored(s):
            return None
        return MAIN_Q_RE.match(s)

    def match_subpart_digit_letter(line):
        return SUBPART_DIGIT_LETTER_RE.match(line.strip())

    def match_subpart_paren(line):
        return SUBPART_PAREN_LETTER_RE.match(line.strip())

    def match_subpart_with_parens(line):
        return SUBPART_WITH_PARENS_RE.match(line.strip())

    # Scan lines and build blocks
    blocks = []
    i = 0
    first_main_seen_at = None

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if is_ignored(stripped):
            i += 1
            continue

        # Detect inline parent+subpart like "1(a) ..."
        m_inline = match_subpart_with_parens(stripped)
        if m_inline:
            qnum = m_inline.group(1)
            letter = m_inline.group(2).lower()
            blocks.append({"type": "parent", "qnum": qnum, "subpart": None, "start": i, "end": None})
            blocks.append({"type": "child", "qnum": qnum, "subpart": letter, "start": i, "end": None})
            if first_main_seen_at is None:
                first_main_seen_at = i
            i += 1
            continue

        # Detect main question
        m = match_main(stripped)
        if m:
            qnum = m.group(1)
            if first_main_seen_at is None and i < min_scan_for_question:
                after = stripped[len(m.group(0)):] if len(stripped) > 0 else ''
                next_line = lines[i+1].strip() if i+1 < n else ""
                looks_like_question = (
                    bool(after and (after[0].isupper() or after[0] in ".-:()")) or
                    (next_line and next_line[:1].isupper())
                )
                if not looks_like_question:
                    i += 1
                    continue

            blocks.append({"type": "parent", "qnum": qnum, "subpart": None, "start": i, "end": None})
            if first_main_seen_at is None:
                first_main_seen_at = i
            i += 1
            continue

        # Detect subpart "3a" format
        m_sd = match_subpart_digit_letter(stripped)
        if m_sd:
            qnum = m_sd.group(1)
            letter = m_sd.group(2).lower()
            parent_exists = any(b for b in blocks if b["type"] == "parent" and b["qnum"] == qnum)
            if not parent_exists:
                print(f"[WARN] Orphan subpart '{stripped}' at line {i}. No prior parent {qnum} found.")
                i += 1
                continue
            blocks.append({"type": "child", "qnum": qnum, "subpart": letter, "start": i, "end": None})
            i += 1
            continue

        # Detect subpart "(a)" format
        m_sp = match_subpart_paren(stripped)
        if m_sp:
            letter = m_sp.group(1).lower()
            last_parent = None
            for b in reversed(blocks):
                if b["type"] == "parent":
                    last_parent = b
                    break
            if not last_parent:
                print(f"[WARN] Orphan parentless subpart '({letter})' at line {i}.")
                i += 1
                continue
            qnum = last_parent["qnum"]
            blocks.append({"type": "child", "qnum": qnum, "subpart": letter, "start": i, "end": None})
            i += 1
            continue

        i += 1

    # Assign end indices
    for idx in range(len(blocks)):
        start = blocks[idx]["start"]
        end = blocks[idx + 1]["start"] if idx + 1 < len(blocks) else n
        blocks[idx]["end"] = end

    # Build extracted blocks with raw text
    extracted = []
    for b in blocks:
        chunk_lines = lines[b["start"]: b["end"]]
        raw = "\n".join(chunk_lines).strip()
        if b["type"] == "child" and not keep_headers:
            stripped_raw = re.sub(r'^\s*(?:\d{1,2}\s*[\.\)\-:]?\s*)?\(?\s*[a-z]\s*\)?[\.\)\:\-\s]*', '', raw, count=1, flags=re.I)
            raw = stripped_raw.strip()
        extracted.append({**b, "raw": raw})

    if verbose:
        print("=== DETECTED PARENT BLOCKS ===")
        for ex in extracted:
            if ex["type"] == "parent":
                hdr = ex["raw"].split("\n", 1)[0]
                print(f"Parent Q{ex['qnum']} @ {ex['start']}: {hdr}")
        print("=== DETECTED CHILD BLOCKS ===")
        for ex in extracted:
            if ex["type"] == "child":
                hdr = ex["raw"].split("\n", 1)[0]
                print(f"Child Q{ex['qnum']}{ex['subpart']} @ {ex['start']}: {hdr}")
        print("=== END DETECTION ===\n")

    # Organize parents -> children
    parents = {}
    for ex in extracted:
        if ex["type"] == "parent":
            parents[ex["qnum"]] = {"parent": ex, "children": []}
        else:
            q = ex["qnum"]
            if q not in parents:
                print(f"[WARN] child for missing parent Q{q} at line {ex['start']} — skipping")
                continue
            parents[q]["children"].append(ex)

    # Warn about anomalies
    for qnum, grp in parents.items():
        subs = [c["subpart"] for c in grp["children"]]
        if subs != sorted(subs):
            print(f"[WARN] Subpart order anomaly for Q{qnum}: {subs}")
        dup = {s for s in subs if subs.count(s) > 1}
        if dup:
            print(f"[WARN] Duplicate subparts for Q{qnum}: {sorted(list(dup))}")

    # Insert into database
    inserted_ids = []
    count = 0

    for qnum, grp in parents.items():
        parent_blk = grp["parent"]
        pid = insert_entry(
            raw_text=parent_blk["raw"],
            parent_id=None,
            subpart=None,
            file_path=meta["file_path"],
            file_type=meta["file_type"],
            purpose=meta["purpose"],
            subject=meta["subject"],
            semester=meta["semester"],
            summary=None,
            status="raw",
        )
        inserted_ids.append(pid)
        count += 1

        for child in grp["children"]:
            cid = insert_entry(
                raw_text=child["raw"],
                parent_id=pid,
                subpart=child["subpart"],
                file_path=meta["file_path"],
                file_type=meta["file_type"],
                purpose=meta["purpose"],
                subject=meta["subject"],
                semester=meta["semester"],
                summary=None,
                status="raw",
            )
            inserted_ids.append(cid)
            count += 1

    if verbose:
        print(f"Inserted {count} rows. IDs: {inserted_ids}")

    return count, inserted_ids
