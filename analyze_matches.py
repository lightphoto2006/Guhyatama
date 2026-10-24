import json
import re
import unicodedata
import difflib
import os
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

PDF_TEXT_FILE = r"F:\AI\тест2\DB\Книги ачарий\pdf_text_by_page.json"
OCR_JSONL_FILE = r"C:\Users\light\AppData\Local\Temp\opencode\ocr\pages_ocr.inline_fixed.jsonl"

LATRE = re.compile(r"[A-Za-z\u0100-\u017F\u1E00-\u1EFF]")
VERSE_NUMBER_PATTERN = re.compile(r'^\d+\.\d+\.')

def normalize(text):
    if not text: return ""
    text = text.lower().strip()
    return "".join(ch for ch in text if unicodedata.category(ch)[0] in ('L', 'N', 'M'))

def is_verse(text):
    text = text.strip()
    if not text: return False
    if VERSE_NUMBER_PATTERN.match(text): return True
    if any(delim in text for delim in ('|', '॥', '।')):
        if LATRE.search(text):
            return True
    return False

def main():
    with open(PDF_TEXT_FILE, 'r', encoding='utf-8') as f:
        pdf_text_by_page = json.load(f)
    with open(OCR_JSONL_FILE, 'r', encoding='utf-8') as f:
        ocr_pages = [json.loads(line) for line in f if line.strip()]

    for page_data in ocr_pages:
        page_num_ocr = page_data['page']
        page_text_ocr = page_data['text']
        page_num_pdf = str(page_num_ocr + 1)
        page_text_pdf = pdf_text_by_page.get(page_num_pdf, "")
        if not page_text_pdf: continue

        pdf_segments = [s.strip() for s in re.split(r'\n|\s{2,}', page_text_pdf) if s.strip()]
        ocr_lines = [l.strip() for l in page_text_ocr.split('\n') if l.strip()]

        for line in ocr_lines:
            if is_verse(line):
                normalized_original = normalize(line)
                if not normalized_original: continue
                
                max_sim = -1.0
                best_seg = None
                for seg in pdf_segments:
                    norm_seg = normalize(seg)
                    if not norm_seg: continue
                    sim = difflib.SequenceMatcher(None, normalized_original, norm_seg).ratio()
                    if sim > max_sim:
                        max_sim = sim
                        best_seg = seg
                
                if max_sim < 0.8: # Print ones with low similarity
                    print(f"PAGE {page_num_pdf} | Verse: {line}")
                    print(f"  Max Sim: {max_sim:.4f} | Best Seg: {best_seg}")
                    if max_sim > 0:
                        print(f"  Top 3 Segs: {[ (normalize(s), difflib.SequenceMatcher(None, normalized_original, normalize(s)).ratio()) for s in pdf_segments if normalize(s)][:3]}")
                    print("-" * 30)

if __name__ == "__main__":
    main()
