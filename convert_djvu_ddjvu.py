# -*- coding: utf-8 -*-
"""
Конвертация DJVU в PDF с помощью ddjvu
"""
import subprocess
import sys
import os

# Настройка кодировки для вывода
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

djvu_path = r'F:\AI\тест2\DB\Книги ачарий\Rupa Gosvami - Bkhakti-rasamrita-sindkhu.djvu'
pdf_path = r'F:\AI\тест2\DB\Книги ачарий\Rupa Gosvami - Bkhakti-rasamrita-sindkhu.pdf'
ddjvu_path = r'C:\Program Files (x86)\DjVuLibre\ddjvu.exe'

print(f"Converting {djvu_path} to PDF...")

try:
    # Используем ddjvu для конвертации в PDF
    result = subprocess.run(
        [ddjvu_path, '-format=pdf', djvu_path, pdf_path],
        capture_output=True,
        text=True,
        timeout=120,
        encoding='utf-8',
        errors='ignore'
    )

    print(f"Return code: {result.returncode}")
    print(f"Output length: {len(result.stdout)} characters")
    print(f"Error length: {len(result.stderr)} characters")

    if result.stdout:
        print(f"Output:")
        print(result.stdout[:1000])
    else:
        print("No output from ddjvu")

    if os.path.exists(pdf_path):
        size = os.path.getsize(pdf_path) / (1024 * 1024)
        print(f"\nPDF created successfully: {pdf_path}")
        print(f"PDF size: {size:.2f} MB")
    else:
        print("\nPDF file was not created")

except Exception as e:
    print(f"Error: {e}")

print("Done")
