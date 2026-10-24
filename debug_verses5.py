import fitz  # PyMuPDF
from docx import Document
import re
import sys

# Set UTF-8 encoding for output
sys.stdout.reconfigure(encoding='utf-8')

# File paths
pdf_path = r"F:\AI\тест2\DB\Книги ачарий\Bhakti-rasamrta-sindhu (Bhanu).pdf"
docx_path = r"F:\AI\тест2\DB\Книги ачарий\Бхакти-расамрита-синдху часть 1 (OCR).docx"

# Open PDF - find page with verse 1.1.1
pdf_doc = fitz.open(pdf_path)

# Try to find the verse by searching for Sanskrit text
for page_num in range(pdf_doc.page_count):
    page = pdf_doc[page_num]
    text = page.get_text()

    # Look for the first verse pattern
    verse_pattern = r'\|\|1\.\d+\.\d+\|\|[^|]*\|'
    matches = re.findall(verse_pattern, text, re.IGNORECASE)

    if matches:
        print(f"Found verse on page {page_num + 1}:")
        print("=" * 80)
        for match in matches[:1]:
            print(f"PDF verse: {match}")
        print("=" * 80)
        break

pdf_doc.close()

# Open DOCX
docx_doc = Document(docx_path)

print("\nDOCX verse 1.1.1:")
print("=" * 80)

for i, para in enumerate(docx_doc.paragraphs):
    text = para.text.strip()
    if '||1.1.1||' in text:
        print(f"Text: {text}")
        print(f"Length: {len(text)}")
        print("=" * 80)
        break
