import re
from typing import Optional

# ---------- Prefix patterns (applied in order; stop after first match) ----------
PREFIX_PATTERNS = [
    re.compile(r'^\s*Q\s*(?:No\.?)?\s*\d+[.)]?\s+', re.IGNORECASE),       # Q-style
    re.compile(r'^\s*\d+(?:\([A-Za-z0-9]+\))?[.)]?\s+'),                  # numeric (1, 3(a), 12.)
    re.compile(r'^\s*\(?[A-Za-z]{1,3}\)?[.)]?\s+'),                       # alphabet short (a), (ii), ii)
    re.compile(r'^\s*[\-\•\*]\s+'),                                       # bullets -, •, *
]

# ---------- Small words to keep lowercased in titlecase (unless first/last) ----------
SMALL_WORDS = {
    "a","an","the","and","but","or","nor","for","so","yet",
    "at","around","by","after","along","for","from","of","on","to","with","without","in","into","over","per","via","vs","vs."
}

# ---------- Known acronyms to always preserve  ----------
KNOWN_ACRONYMS = {"ACID","SQL","BCNF","ERD","API","HTTP","URL","ID","CSV","XML","JSON"}

# ---------- Helpers ----------

def _normalize_whitespace(s: str) -> str:
    s = s.replace('\r', ' ').replace('\n', ' ')
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

def _first_sentence_or_fallback(text: str, fallback_words: int = 12, max_sentence_len: int = 240) -> str:
    """
    Attempt to extract the first sentence (up to ., ?, !).
    If no sentence-like punctuation is found within a reasonable window,
    fall back to first `fallback_words` words.
    """
    text = _normalize_whitespace(text)
    if not text:
        return text

    m = re.search(r'(.{1,%d}?[\.\?\!])(?:\s|$)' % max_sentence_len, text)
    if m:
        candidate = m.group(1).strip()
        candidate = re.sub(r'^[\'"\(\[]+|[\'"\)\]]+$', '', candidate).strip()
        if len(candidate.split()) <= 40:
            return candidate

    words = text.split()
    if len(words) <= fallback_words:
        return text
    else:
        return ' '.join(words[:fallback_words])

def _strip_prefix_once(text: str) -> str:
    """Apply prefix patterns in order, stop after first successful substitution."""
    for pat in PREFIX_PATTERNS:
        new = pat.sub("", text, count=1)
        if new != text:
            return new
    return text

def _is_acronym(token: str) -> bool:
    if token.upper() in KNOWN_ACRONYMS:
        return True
    pure = re.sub(r'[^A-Za-z]', '', token)
    return len(pure) >= 2 and pure.isupper()

def _titlecase_preserve_acronyms(s: str) -> str:
    """
    Title-case while preserving:
      - known acronyms (ACID, SQL, etc.)
      - fully uppercase tokens (likely acronyms)
    Also keeps small words lowercased unless they're first or last.
    """
    tokens = s.split()
    if not tokens:
        return s

    out_tokens = []
    for i, tok in enumerate(tokens):
        # preserve punctuation attached; work on word core
        prefix_match = re.match(r'^([\'"\(\[]*)(.*?)([\'"\)\]\,:;]*)$', tok)
        if prefix_match:
            pre, core, post = prefix_match.groups()
        else:
            pre, core, post = '', tok, ''

        # if core contains digits or slashes (e.g., "iPhone", "v2.0", "BCNF/3"), handle simply
        if _is_acronym(core):
            new_core = core.upper()
        else:
            lower_core = core.lower()
            if (i != 0 and i != len(tokens)-1) and lower_core in SMALL_WORDS:
                new_core = lower_core
            else:
                # Capitalize first alpha char, leave rest as-is except force rest lower for readability
                if core:
                    new_core = core[0].upper() + core[1:].lower()
                else:
                    new_core = core

        out_tokens.append(f"{pre}{new_core}{post}")

    return ' '.join(out_tokens)

def _final_sanitize(title: str, max_len: int = 120) -> str:
    # remove leftover line breaks, collapse spaces
    t = _normalize_whitespace(title)

    # remove trailing punctuation like :, -, ., ,, ; (but keep acronyms with .? unlikely)
    t = re.sub(r'[\:\-\–\—\.,;]+$','', t).strip()

    # trim to max length without chopping a word if possible
    if len(t) > max_len:
        # try to cut at last space before max_len
        cut = t[:max_len].rstrip()
        last_space = cut.rfind(' ')
        if last_space > 0:
            t = cut[:last_space]
        else:
            t = cut

        t = t.rstrip('.,:;:-')

    # final collapse and strip
    t = _normalize_whitespace(t)
    return t

# ---------- Public function: full pipeline ----------
def extract_title(text: Optional[str],
                  fallback_words: int = 12,
                  max_len: int = 120) -> str:
    """
    Full title extraction pipeline:
      1) Normalize & extract first sentence (or fallback first N words)
      2) Remove a single prefix using multiple targeted regexes (stop after first)
      3) Title-case while preserving acronyms and small-words rules
      4) Final sanitization: trailing punctuation, collapse spaces, trim length
    """
    if text is None:
        return "Untitled Entry"

    # Step 0: normalize whitespace early
    normalized = _normalize_whitespace(text)
    if not normalized:
        return "Untitled Entry"

    # Step 1: extract first sentence OR fallback
    title_chunk = _first_sentence_or_fallback(normalized, fallback_words=fallback_words)

    # Step 2 (prefix cleanup): strip only one prefix (stop after first match)
    after_prefix = _strip_prefix_once(title_chunk)

    # Step 2b: extra safety — if result is empty or looks like garbage, fall back to the very first words
    if not after_prefix or len(after_prefix.split()) < 1:
        after_prefix = ' '.join(normalized.split()[:fallback_words])

    # Step 3: Title-case normalization (preserve acronyms)
    title_cased = _titlecase_preserve_acronyms(after_prefix)

    # Step 4: Final sanitization
    final = _final_sanitize(title_cased, max_len)

    if not final:
        return "Untitled Entry"
    return final

