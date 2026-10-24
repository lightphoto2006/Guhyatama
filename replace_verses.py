import fitz  # PyMuPDF
from docx import Document
import os
import re
import sys

# Set UTF-8 encoding for output
sys.stdout.reconfigure(encoding='utf-8')

# File paths
pdf_path = r"F:\AI\тест2\DB\Книги ачарий\Bhakti-rasamrta-sindhu (Bhanu).pdf"
docx_path = r"F:\AI\тест2\DB\Книги ачарий\Бхакти-расамрита-синдху часть 1 (OCR).docx"
output_path = r"F:\AI\тест2\DB\Книги ачарий\Бхакти-расамрита-синдху часть 1 (OCR)_3.docx"

print("=" * 80)
print("STEP 1: Extracting verses from PDF")
print("=" * 80)

# Extract verses from PDF
pdf_verses = {}
pdf_paragraphs = []

# Open PDF
pdf_doc = fitz.open(pdf_path)
print(f"PDF pages: {pdf_doc.page_count}")

# Extract text from all pages
for page_num in range(pdf_doc.page_count):
    page = pdf_doc[page_num]
    text = page.get_text()
    pdf_paragraphs.append(text)

# Extract verses based on markers
verse_pattern = r'\|\|.*?\|\||\d+\.\d+|॥'
for i, para in enumerate(pdf_paragraphs):
    # Check if paragraph contains verse markers
    if re.search(verse_pattern, para):
        # Extract the verse - get the entire block of text that contains the marker
        # We'll take the whole paragraph since we're iterating through chunks
        pdf_verses[para] = para
        print(f"\nPDF Verse {i+1}:")
        print(f"Length: {len(para)} chars")
        print(f"Preview: {para[:100]}...")

print(f"\nTotal verses found in PDF: {len(pdf_verses)}")

print("\n" + "=" * 80)
print("STEP 2: Extracting verses from DOCX")
print("=" * 80)

# Extract verses from DOCX
docx_doc = Document(docx_path)
docx_paragraphs = list(docx_doc.paragraphs)

docx_verses = {}
for i, para in enumerate(docx_paragraphs):
    text = para.text.strip()
    if not text:
        continue

    # Check if paragraph is a verse
    is_verse = (
        para.alignment == 1 or  # Center alignment
        '||' in text or
        '॥' in text or
        '.' in text or  # Verse number pattern
        len(text) > 20  # Likely a verse (Sanskrit text is usually longer)
    )

    if is_verse:
        docx_verses[text] = text
        print(f"\nDOCX Verse {i+1}:")
        print(f"Text: {text[:100]}...")
        print(f"Alignment: {para.alignment}")

print(f"\nTotal verses found in DOCX: {len(docx_verses)}")

print("\n" + "=" * 80)
print("STEP 3: Performing replacement")
print("=" * 80)

# Create new DOCX by copying the original
new_doc = Document(docx_path)

replaced_count = 0
not_found_count = 0

for i, para in enumerate(new_doc.paragraphs):
    text = para.text.strip()
    if not text:
        continue

    # Check if this paragraph is a verse in DOCX
    is_verse = (
        para.alignment == 1 or  # Center alignment
        '||' in text or
        '॥' in text or
        '.' in text or
        len(text) > 20
    )

    if is_verse:
        # Check if exact match exists in PDF verses
        if text in pdf_verses:
            # Replace entire paragraph with PDF text
            # Remove all runs and add new one with PDF text
            for run in para.runs:
                run.text = pdf_verses[text]
                run._element.getparent().remove(run._element)

            replaced_count += 1
            print(f"\n✓ Replaced paragraph {i+1}")
            print(f"  Old: {text[:80]}...")
            print(f"  New: {pdf_verses[text][:80]}...")
        else:
            not_found_count += 1
            print(f"\n✗ No match in PDF for paragraph {i+1}")
            print(f"  Text: {text[:80]}...")

print("\n" + "=" * 80)
print("STEP 4: Saving new file")
print("=" * 80)

new_doc.save(output_path)
print(f"Saved to: {output_path}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"Verses found in PDF: {len(pdf_verses)}")
print(f"Verses found in DOCX: {len(docx_verses)}")
print(f"Verses replaced: {replaced_count}")
print(f"Verses not found in PDF: {not_found_count}")
print("=" * 80)

pdf_doc.close()
