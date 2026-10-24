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

# Get page count
print(f"PDF has {pdf_doc.page_count} pages\n")

# Try to find the verse by searching
for page_num in range(pdf_doc.page_count):
    page = pdf_doc[page_num]
    text = page.get_text()

    if 'akhila-rasāmṛta-mūrtiḥ' in text.lower() or 'akila-rasamrita-murti' in text.lower():
        print(f"Found verse 1.1.1 on page {page_num + 1}")
        print("=" * 80)
        # Extract the verse (look for ||1.1.1||)
        verse_pattern = r'\|\|1\.1\.1\|\|[^|]*\|'
        match = re.search(verse_pattern, text, re.IGNORECASE)
        if match:
            print(f"PDF verse: {match.group()}")
        else:
            # Try broader search
            start = text.find('||')
            if start != -1:
                end = text.find('||', start + 2)
                if end != -1:
                    print(f"PDF verse: {text[start:end+2]}")
        print("=" * 80)
        break
    elif '||1.2.18||' in text:
        print(f"Found verse 1.2.18 on page {page_num + 1}")
        print("=" * 80)
        verse_pattern = r'\|\|1\.2\.18\|\|[^|]*\|'
        match = re.search(verse_pattern, text, re.IGNORECASE)
        if match:
            print(f"PDF verse: {match.group()}")
        else:
            # Try broader search
            start = text.find('||')
            if start != -1:
                end = text.find('||', start + 2)
                if end != -1:
                    print(f"PDF verse: {text[start:end+2]}")
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
