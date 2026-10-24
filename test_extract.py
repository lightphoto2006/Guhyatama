import re
import unicodedata

LATRE = re.compile(r"[A-Za-z\u0100-\u017F\u1E00-\u1EFF]")
VERSE_NUMBER_REGEX = r'\d+(?:\.\d+)+'
VERSE_NUMBER_PATTERN = re.compile(r'^' + VERSE_NUMBER_REGEX)
SEGMENT_PATTERN = re.compile(r'(\|\||॥|' + VERSE_NUMBER_REGEX + ').*?(?=\|\||॥|' + VERSE_NUMBER_REGEX + '|$)', re.DOTALL)

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

def extract_all_verses_from_text(text):
    verses = []
    for match in SEGMENT_PATTERN.finditer(text):
        segment = match.group(0).strip()
        if is_verse(segment):
            verses.append(segment)
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        if is_verse(line):
            verses.append(line)
    return verses

import time
test_text = "1.1. Verse one | 1.2. Verse two ॥ 1.3. Verse three\n4.4. Another verse | some text\n| 5.5. More verse" * 1000
start = time.time()
res = extract_all_verses_from_text(test_text)
end = time.time()
print(f"Found {len(res)} verses in {end-start:.4f} seconds")
