import fitz  # PyMuPDF
from docx import Document
import re
import sys

# Set UTF-8 encoding for output
sys.stdout.reconfigure(encoding='utf-8')

# File paths
pdf_path = r"F:\AI\тест2\DB\Книги ачарий\Bhakti-rasamrta-sindhu (Bhanu).pdf"
docx_path = r"F:\AI\тест2\DB\Книги ачарий\Бхакти-расамрита-синдху часть 1 (OCR).docx"

# Open PDF - find verse 2.1.153
pdf_doc = fitz.open(pdf_path)

for page_num in range(pdf_doc.page_count):
    page = pdf_doc[page_num]
    text = page.get_text()

    if '2.1.153' in text:
        print(f"Found verse 2.1.153 on page {page_num + 1}")
        print("=" * 80)
        verse_pattern = r'\|\|2\.1\.153\|\|[^|]*\|[^|]*\n|[^|]*\|\|2\.1\.153\|[^|]*\n'
        matches = re.findall(verse_pattern, text, re.IGNORECASE)
        for match in matches[:1]:
            print(f"PDF verse: {match}")
        print("=" * 80)
        break

pdf_doc.close()

# Open DOCX - find verse 2.1.153
docx_doc = Document(docx_path)

print("\nDOCX verse 2.1.153:")
print("=" * 80)

for i, para in enumerate(docx_doc.paragraphs):
    text = para.text.strip()
    if '||2.1.153||' in text:
        print(f"Text: {text}")
        print(f"Length: {len(text)}")
        print("=" * 80)
        break
