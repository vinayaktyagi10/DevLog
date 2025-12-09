import re
import unicodedata

_WEIRD_WHITESPACE_RE = re.compile(
        r"[\u00A0\u1680\u2000-\u200A\u202F\u205F\u3000\u200B-\u200D\ufeff]"
        )
def normalize_text(text: str) -> str:
    if text is None:
        return ""

    text=unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WEIRD_WHITESPACE_RE.sub(" ", text)
    text = text.replace("\t", " ")
    lines = text.splitlines()
    processed_lines = []
    last_was_blank = False
    for raw_line in lines:
        line = raw_line.strip()
        line=re.sub(r" {2,}", " ", line)
        if line == "":
            if not last_was_blank and processed_lines:
                processed_lines.append("")
            last_was_blank = True
        else:
            processed_lines.append(line)
            last_was_blank = False
    normalized = "\n".join(processed_lines)
    normalized = normalized.strip()
    return normalized

