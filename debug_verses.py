import fitz  # PyMuPDF
from docx import Document
import re
import sys

# Set UTF-8 encoding for output
sys.stdout.reconfigure(encoding='utf-8')

# File paths
pdf_path = r"F:\AI\тест2\DB\Книги ачарий\Bhakti-rasamrta-sindhu (Bhanu).pdf"
docx_path = r"F:\AI\тест2\DB\Книги ачарий\Бхакти-расамрита-синдху часть 1 (OCR).docx"

# Open PDF
pdf_doc = fitz.open(pdf_path)
page = pdf_doc[0]
text = page.get_text()

print("PDF Page 1 text:")
print("=" * 80)
print(text[:2000])
print("=" * 80)

# Try to find verse pattern
verse_pattern = r'\|\|.*?\|\||\d+\.\d+|॥'
matches = re.findall(verse_pattern, text)
print(f"\nFound {len(matches)} verse patterns in first page")

if matches:
    print(f"\nFirst match: {matches[0]}")

pdf_doc.close()

# Open DOCX
docx_doc = Document(docx_path)
print("\n" + "=" * 80)
print("DOCX Paragraph 1:")
print("=" * 80)
for i, para in enumerate(docx_doc.paragraphs[:10]):
    text = para.text.strip()
    if text:
        print(f"{i}: {text[:200]}...")
