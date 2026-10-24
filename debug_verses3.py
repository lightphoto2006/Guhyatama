import fitz  # PyMuPDF
from docx import Document
import re
import sys

# Set UTF-8 encoding for output
sys.stdout.reconfigure(encoding='utf-8')

# File paths
pdf_path = r"F:\AI\тест2\DB\Книги ачарий\Bhakti-rasamrta-sindhu (Bhanu).pdf"
docx_path = r"F:\AI\тест2\DB\Книги ачарий\Бхакти-расамрита-синдху часть 1 (OCR).docx"

# Open PDF - check pages around where verses should be
pdf_doc = fitz.open(pdf_path)
page = pdf_doc[100]  # Check page 100
text = page.get_text()

print("PDF Page 100 text:")
print("=" * 80)
# Print only first 3000 chars
print(text[:3000])
print("...")
print("=" * 80)

# Try to find verse pattern
verse_pattern = r'\|\|.*?\|\||\d+\.\d+|॥'
matches = re.findall(verse_pattern, text)
print(f"\nFound {len(matches)} verse patterns in page 100")

if matches:
    print(f"\nFirst 5 matches:")
    for i, match in enumerate(matches[:5]):
        print(f"{i+1}. {match}")

pdf_doc.close()

# Open DOCX - find the first verse
docx_doc = Document(docx_path)
print("\n" + "=" * 80)
print("DOCX Paragraph with ||1.1.1||:")
print("=" * 80)

for i, para in enumerate(docx_doc.paragraphs):
    text = para.text.strip()
    if '||1.1.1||' in text:
        print(f"\nParagraph {i}:")
        print(f"Text: {text}")
        print(f"Alignment: {para.alignment}")
        print(f"Length: {len(text)}")
        break
