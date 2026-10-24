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
        print(f"Found '2.1.153' on page {page_num + 1}")
        print("=" * 80)

        # Find the marker and surrounding text
        start = text.find('||')
        end = text.find('||', start + 2)
        if end != -1:
            print(f"Context around marker: {text[start:end+2]}")
            print(f"Length: {end - start + 2} chars")

        # Try to find the verse text
        verse_pattern = r'\|\|[\d.]+\|\|[^|]*\|[^|]*\n|[^|]*\|\|[\d.]+\|[^|]*\n'
        matches = re.findall(verse_pattern, text, re.IGNORECASE)
        for match in matches:
            if '2.1.153' in match or '2.1.15' in match:
                print(f"Verse found: {match}")
                break
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
        print(f"Text: {repr(text)}")
        print(f"Length: {len(text)}")
        print("=" * 80)
        break
