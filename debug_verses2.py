import fitz  # PyMuPDF
from docx import Document
import re
import sys

# Set UTF-8 encoding for output
sys.stdout.reconfigure(encoding='utf-8')

# File paths
pdf_path = r"F:\AI\тест2\DB\Книги ачарий\Bhakti-rasamrta-sindhu (Bhanu).pdf"
docx_path = r"F:\AI\тест2\DB\Книги ачарий\Бхакти-расамрита-синдху часть 1 (OCR).docx"

# Open PDF - check pages around the middle
pdf_doc = fitz.open(pdf_path)
page = pdf_doc[50]  # Check page 50
text = page.get_text()

print("PDF Page 50 text:")
print("=" * 80)
print(text)
print("=" * 80)

pdf_doc.close()

# Open DOCX - find verses
docx_doc = Document(docx_path)
print("\n" + "=" * 80)
print("DOCX Paragraphs with verse markers:")
print("=" * 80)

verse_count = 0
for i, para in enumerate(docx_doc.paragraphs):
    text = para.text.strip()
    if not text:
        continue

    is_verse = (
        '||' in text or
        '॥' in text or
        '.' in text
    )

    if is_verse and verse_count < 20:
        verse_count += 1
        print(f"\nVerse {verse_count} (para {i}):")
        print(f"Text: {text}")
        print(f"Alignment: {para.alignment}")
        print(f"Length: {len(text)}")
