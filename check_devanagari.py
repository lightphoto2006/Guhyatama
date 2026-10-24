import fitz
import re

pdf_path = r'F:\AI\тест2\DB\Книги ачарий\Bhakti-rasamrta-sindhu (Bhanu).pdf'
doc = fitz.open(pdf_path)
count = 0
for i in range(len(doc)):
    text = doc[i].get_text()
    if re.search(r'[\u0900-\u097F]', text):
        count += 1
print(f"Pages with Devanagari: {count}")
doc.close()
