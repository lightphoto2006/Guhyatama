import json
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

OCR_JSONL_FILE = r"C:\Users\light\AppData\Local\Temp\opencode\ocr\pages_ocr.inline_fixed.jsonl"

with open(OCR_JSONL_FILE, 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data['page'] == 619:
            print(f"OCR PAGE 619 TEXT:\n{data['text']}")
            break
