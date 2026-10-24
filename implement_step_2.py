import json
import re
import unicodedata
import difflib
import os
import sys

# Ensure stdout supports UTF-8 for Cyrillic
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# --- Configuration ---
PDF_TEXT_FILE = r"F:\AI\тест2\DB\Книги ачарий\pdf_text_by_page.json"
OCR_JSONL_FILE = r"C:\Users\light\AppData\Local\Temp\opencode\ocr\pages_ocr.inline_fixed.jsonl"
OUTPUT_FILE = r"F:\AI\тест2\DB\Книги ачарий\verse_mapping.json"

# Regex patterns
LATRE = re.compile(r"[A-Za-z\u0100-\u017F\u1E00-\u1EFF]")
VERSE_NUMBER_REGEX = r'\d+(?:\.\d+)+'
VERSE_NUMBER_PATTERN = re.compile(r'^' + VERSE_NUMBER_REGEX)
# This pattern groups text between delimiters (||, ॥, or verse numbers)
SEGMENT_PATTERN = re.compile(r'(\|\||॥|' + VERSE_NUMBER_REGEX + ').*?(?=\|\||॥|' + VERSE_NUMBER_REGEX + '|$)', re.DOTALL)

# --- Functions ---

def normalize(text):
    """
    Creates a normalized version: lowercase, strip whitespace, 
    remove all non-alphanumeric/non-diacritic characters.
    """
    if not text:
        return ""
    text = text.lower().strip()
    # L = Letter, N = Number, M = Mark (diacritics)
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in ('L', 'N', 'M'))

def is_verse(text):
    """
    A paragraph is a verse if it contains '|', '॥', or '।' 
    AND contains Latin/transliteration characters (LATRE regex), 
    OR if it matches a verse numbering pattern.
    """
    text = text.strip()
    if not text:
        return False
    
    # Check for numbering pattern first
    if VERSE_NUMBER_PATTERN.match(text):
        return True
        
    # Check for delimiters AND Latin characters
    if any(delim in text for delim in ('|', '॥', '।')):
        if LATRE.search(text):
            return True
            
    return False

def main():
    # 1. Load Data
    print(f"Loading PDF text from {PDF_TEXT_FILE}...")
    if not os.path.exists(PDF_TEXT_FILE):
        print(f"Error: PDF text file not found at {PDF_TEXT_FILE}")
        return
    with open(PDF_TEXT_FILE, 'r', encoding='utf-8') as f:
        pdf_text_by_page = json.load(f)

    print(f"Loading OCR JSONL from {OCR_JSONL_FILE}...")
    if not os.path.exists(OCR_JSONL_FILE):
        print(f"Error: OCR JSONL file not found at {OCR_JSONL_FILE}")
        return
    ocr_pages = []
    with open(OCR_JSONL_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                ocr_pages.append(json.loads(line))

    # 3. Matching Logic (Optimized)
    verse_mapping = {}
    total_verses_found = 0
    total_matched = 0
    total_failed = 0

    print("Starting matching process...")

    for page_data in ocr_pages:
        page_num_ocr = page_data['page']
        page_text_ocr = page_data['text']
        
        # PDF pages are usually 1-indexed in the JSON, 
        # while OCR 'page' is often 0-indexed.
        page_num_pdf = str(page_num_ocr + 1)
        page_text_pdf = pdf_text_by_page.get(page_num_pdf, "")

        if not page_text_pdf:
            continue

        # Pre-process PDF page text: Split into candidates
        # We include both newline-split lines and segments grouped by delimiters
        candidates = []
        candidates.extend([c.strip() for c in page_text_pdf.split('\n') if c.strip()])
        for match in SEGMENT_PATTERN.finditer(page_text_pdf):
            candidates.append(match.group(0).strip())
        
        candidates = list(set(candidates)) # Remove duplicates

        # Identify all verses in that page's text (split OCR text into lines)
        ocr_lines = [l.strip() for l in page_text_ocr.split('\n') if l.strip()]

        for line in ocr_lines:
            if is_verse(line):
                total_verses_found += 1
                normalized_original = normalize(line)
                
                # To ensure the verse number doesn't ruin the similarity score,
                # we create a version without the verse number for comparison.
                # This aligns with the intent of matching the verse text.
                normalized_original_for_sim = normalize(re.sub(r'\d+(?:\.\d+)+', '', line))
                
                if not normalized_original_for_sim:
                    total_failed += 1
                    continue

                best_match_segment = None
                max_similarity = -1.0

                for candidate in candidates:
                    normalized_candidate = normalize(candidate)
                    if not normalized_candidate:
                        continue
                    
                    similarity = difflib.SequenceMatcher(None, normalized_original_for_sim, normalized_candidate).ratio()
                    
                    if similarity > max_similarity:
                        max_similarity = similarity
                        best_match_segment = candidate

                # Threshold: > 0.6
                if max_similarity > 0.6:
                    verse_mapping[line] = best_match_segment
                    total_matched += 1
                else:
                    total_failed += 1

    # 4. Save Results
    print(f"Saving results to {OUTPUT_FILE}...")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(verse_mapping, f, ensure_ascii=False, indent=4)

    # 5. Report
    print("\n--- Report ---")
    print(f"Total verses found in JSONL: {total_verses_found}")
    print(f"Total verses successfully matched: {total_matched}")
    print(f"Total verses failed to match: {total_failed}")
    print(f"Path to verse_mapping.json: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
