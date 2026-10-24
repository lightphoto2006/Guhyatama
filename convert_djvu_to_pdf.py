# -*- coding: utf-8 -*-
"""
Конвертация DJVU в PDF с помощью SumatraPDF
"""
import subprocess
import os
import sys
import fitz  # pymupdf

# Настройка кодировки для вывода
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

djvu_path = r'F:\AI\тест2\DB\Книги ачарий\Rupa Gosvami - Bkhakti-rasamrita-sindkhu.djvu'
pdf_path = r'F:\AI\тест2\DB\Книги ачарий\Rupa Gosvami - Bkhakti-rasamrita-sindkhu.pdf'

# Конвертация DJVU в PDF через SumatraPDF
sumatrapdf_path = r'C:\Users\light\AppData\Local\SumatraPDF\SumatraPDF.exe'
print(f"Converting {djvu_path} to PDF...")
try:
    # Используем SumatraPDF для конвертации
    result = subprocess.run(
        [sumatrapdf_path, '-extract-text', djvu_path, pdf_path],
        capture_output=True,
        text=True,
        timeout=120
    )
    print(f"SumatraPDF output: {result.stdout}")
    print(f"SumatraPDF error: {result.stderr}")
    print(f"Return code: {result.returncode}")

    if os.path.exists(pdf_path):
        print(f"PDF created successfully: {pdf_path}")
        # Проверяем, сколько страниц в PDF
        doc = fitz.open(pdf_path)
        print(f"Total pages: {doc.page_count}")
        doc.close()
    else:
        print("PDF file was not created")
except Exception as e:
    print(f"Error during conversion: {e}")

print("Conversion complete")
