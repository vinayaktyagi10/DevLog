import fitz

def extract_pdf_text(path):
    doc = fitz.open(path)
    pages = []
    for page in doc:
        pages.append(page.get_text("text"))
    return "\n".join(pages)
