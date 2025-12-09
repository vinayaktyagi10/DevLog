def extract_markdown(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

