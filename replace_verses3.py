import fitz  # PyMuPDF
from docx import Document
import re
import sys

# Set UTF-8 encoding for output
sys.stdout.reconfigure(encoding='utf-8')

# File paths
pdf_path = r"F:\AI\тест2\DB\Книги ачарий\Bhakti-rasamrta-sindhu (Bhanu).pdf"
docx_path = r"F:\AI\тест2\DB\Книги ачарий\Бхакти-расамрита-синдху часть 1 (OCR).docx"
output_path = r"F:\AI\тест2\DB\Книги ачарий\Бхакти-расамрита-синдху часть 1 (OCR)_3.docx"

print("=" * 80)
print("STEP 1: Extracting verses from PDF by verse number")
print("=" * 80)

# Extract verses from PDF
pdf_verses_by_number = {}

# Open PDF
pdf_doc = fitz.open(pdf_path)
print(f"PDF pages: {pdf_doc.page_count}")

# Get all text from all pages
full_pdf_text = ""
for page_num in range(pdf_doc.page_count):
    page = pdf_doc[page_num]
    text = page.get_text()
    full_pdf_text += text + "\n"

# Extract verses by finding all ||...|| patterns and extracting the number
# Pattern: ||1.1.1||, ||2.1.153||, etc.
verse_pattern = r'\|\|(\d+\.\d+\.\d+)\|\|'

for match in re.finditer(verse_pattern, full_pdf_text):
    verse_number = match.group(1)
    start_pos = match.start()

    # Find the end of this verse (next || marker or end of text)
    next_marker = re.search(r'\|\|[\d.]+\|\|', full_pdf_text[start_pos + len(match.group()):])
    if next_marker:
        end_pos = start_pos + len(match.group()) + next_marker.start()
    else:
        end_pos = len(full_pdf_text)

    verse_text = full_pdf_text[start_pos:end_pos].strip()

    # Clean up the text (remove extra newlines within the verse)
    verse_text = re.sub(r'\n\s*\n', '\n', verse_text)
    verse_text = verse_text.strip()

    if verse_text and len(verse_text) > 10:
        pdf_verses_by_number[verse_number] = verse_text
        if len(pdf_verses_by_number) <= 5:  # Show first 5
            print(f"\nPDF Verse {verse_number}:")
            print(f"Length: {len(verse_text)} chars")
            print(f"Preview: {verse_text[:100]}...")

print(f"\nTotal verses found in PDF: {len(pdf_verses_by_number)}")

print("\n" + "=" * 80)
print("STEP 2: Extracting verses from DOCX by verse number")
print("=" * 80)

# Extract verses from DOCX
docx_doc = Document(docx_path)
docx_paragraphs = list(docx_doc.paragraphs)

docx_verses_by_number = {}
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
        # Extract verse number from text
        verse_match = re.search(r'\|\|(\d+\.\d+\.\d+)\|\|', text)
        if verse_match:
            verse_number = verse_match.group(1)
            docx_verses_by_number[verse_number] = text
            if len(docx_verses_by_number) <= 5:  # Show first 5
                print(f"\nDOCX Verse {verse_number}:")
                print(f"Text: {text[:100]}...")
                print(f"Alignment: {para.alignment}")

print(f"\nTotal verses found in DOCX: {len(docx_verses_by_number)}")

print("\n" + "=" * 80)
print("STEP 3: Performing replacement by verse number")
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
        # Extract verse number from text
        verse_match = re.search(r'\|\|(\d+\.\d+\.\d+)\|\|', text)
        if verse_match:
            verse_number = verse_match.group(1)

            # Check if this verse number exists in PDF verses
            if verse_number in pdf_verses_by_number:
                # Replace entire paragraph with PDF text
                for run in para.runs:
                    run.text = pdf_verses_by_number[verse_number]
                    run._element.getparent().remove(run._element)

                replaced_count += 1
                print(f"\n✓ Replaced verse {verse_number} at paragraph {i+1}")
                print(f"  Old: {text[:80]}...")
                print(f"  New: {pdf_verses_by_number[verse_number][:80]}...")
            else:
                not_found_count += 1

print("\n" + "=" * 80)
print("STEP 4: Saving new file")
print("=" * 80)

new_doc.save(output_path)
print(f"Saved to: {output_path}")

print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"Verses found in PDF: {len(pdf_verses_by_number)}")
print(f"Verses found in DOCX: {len(docx_verses_by_number)}")
print(f"Verses replaced: {replaced_count}")
print(f"Verses not found in PDF: {not_found_count}")
print("=" * 80)

pdf_doc.close()
