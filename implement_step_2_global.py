import json
import re
import unicodedata
import difflib
import os
import sys
from collections import defaultdict

# Ensure stdout supports UTF-8
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
    A block is a verse if it has a marker ('|', '॥', or '।') 
    and Latin/transliteration characters, OR if it matches a verse numbering pattern.
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

def extract_all_verses_from_text(text):
    """
    Extracts all verses from a given text block using the specified logic.
    """
    verses = []
    
    # Find segments starting with markers/numbers
    for match in SEGMENT_PATTERN.finditer(text):
        segment = match.group(0).strip()
        if is_verse(segment):
            verses.append(segment)
            
    # Also split by newline to catch any verses that might not follow the SEGMENT_PATTERN
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if is_verse(line):
            # Avoid adding if it was already added by SEGMENT_PATTERN
            if not any(line in v for v in verses):
                verses.append(line)
            
    return verses

def jaccard_similarity(set1, set2):
    if not set1 or not set2:
        return 0.0
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return intersection / union

def get_ngrams(text, n=3):
    if len(text) < n:
        return {text}
    return set(text[i:i+n] for i in range(len(text) - n + 1))

def main():
    # 1. Load Inputs
    print(f"Loading PDF text from {PDF_TEXT_FILE}...")
    if not os.path.exists(PDF_TEXT_FILE):
        print(f"Error: PDF text file not found at {PDF_TEXT_FILE}")
        return
    with open(PDF_TEXT_FILE, 'r', encoding='utf-8') as f:
        pdf_data = json.load(f)

    print(f"Loading JSONL from {OCR_JSONL_FILE}...")
    if not os.path.exists(OCR_JSONL_FILE):
        print(f"Error: OCR JSONL file not found at {OCR_JSONL_FILE}")
        return
    
    all_jsonl_verses = []
    with open(OCR_JSONL_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                page_data = json.loads(line)
                page_text = page_data.get('text', '')
                all_jsonl_verses.extend(extract_all_verses_from_text(page_text))

    # 2. Extract All Verses from PDF (Global)
    print("Extracting all verses from PDF...")
    all_pdf_verses = []
    for page_num_str, page_text in pdf_data.items():
        all_pdf_verses.extend(extract_all_verses_from_text(page_text))

    # 3. Perform Global Similarity Match
    print(f"Found {len(all_jsonl_verses)} verses in JSONL.")
    print(f"Found {len(all_pdf_verses)} verses in PDF.")
    
    unique_pdf_verses = list(set(all_pdf_verses))
    print(f"Unique PDF verses to compare against: {len(unique_pdf_verses)}")
    
    pdf_by_len = defaultdict(list)
    print("Pre-calculating PDF verse features...")
    for v_pdf in unique_pdf_verses:
        norm_pdf = normalize(v_pdf)
        if norm_pdf:
            ngrams = get_ngrams(norm_pdf)
            pdf_by_len[len(norm_pdf)].append((v_pdf, norm_pdf, ngrams))

    mapping = {}
    total_matched = 0
    total_jsonl = len(all_jsonl_verses)
    
    print("Starting global similarity matching (optimized with Jaccard filter and length blocking)...")
    
    for idx, v_jsonl in enumerate(all_jsonl_verses):
        if idx % 100 == 0:
            print(f"  Processing {idx}/{total_jsonl}...")
            
        norm_v_jsonl = normalize(v_jsonl)
        if len(norm_v_jsonl) < 10:
            continue
            
        ngrams_jsonl = get_ngrams(norm_v_jsonl)
        L = len(norm_v_jsonl)
        
        best_v_pdf = None
        max_similarity = 0.0
        
        # Candidates via length blocking + Jaccard filter
        candidates = []
        for length in range(L - 30, L + 31):
            if length in pdf_by_len:
                for v_pdf, norm_pdf, ngrams_pdf in pdf_by_len[length]:
                    if jaccard_similarity(ngrams_jsonl, ngrams_pdf) > 0.2:
                        candidates.append((v_pdf, norm_pdf))
        
        # Final scoring with SequenceMatcher on candidates
        for v_pdf, norm_pdf in candidates:
            similarity = difflib.SequenceMatcher(None, norm_v_jsonl, norm_pdf).ratio()
            if similarity > max_similarity:
                max_similarity = similarity
                best_v_pdf = v_pdf
        
        if max_similarity > 0.7:
            mapping[v_jsonl] = best_v_pdf
            total_matched += 1

    # 4. Save Results
    print(f"Saving results to {OUTPUT_FILE}...")
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=4)

    # 5. Report
    print("\n--- Final Report ---")
    print(f"Total verses found in JSONL: {len(all_jsonl_verses)}")
    print(f"Total verses found in PDF: {len(all_pdf_verses)}")
    print(f"Total successful matches: {total_matched}")
    print(f"Path to verse_mapping.json: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
