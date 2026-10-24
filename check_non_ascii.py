import pdfplumber
import re

pdf_path = r'F:\AI\тест2\DB\Книги ачарий\Bhakti-rasamrta-sindhu (Bhanu).pdf'
with pdfplumber.open(pdf_path) as pdf:
    page = pdf.pages[5]
    text = page.extract_text()
    print(f"Text on page 5: {repr(text)}")
    
    # Check for any non-ASCII
    non_ascii = re.findall(r'[^\x00-\x7F]', text if text else "")
    print(f"Non-ASCII characters found: {len(non_ascii)}")
    if non_ascii:
        print(f"First few: {repr(non_ascii[:10])}")
