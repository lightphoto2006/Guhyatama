import pdfplumber
import re

pdf_path = r'F:\AI\тест2\DB\Книги ачарий\Bhakti-rasamrta-sindhu (Bhanu).pdf'
count = 0
with pdfplumber.open(pdf_path) as pdf:
    for i, page in enumerate(pdf.pages):
        text = page.extract_text()
        if text and re.search(r'[\u0900-\u097F]', text):
            count += 1
print(f"Pages with Devanagari (pdfplumber): {count}")
