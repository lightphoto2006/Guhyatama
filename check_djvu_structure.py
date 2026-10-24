# -*- coding: utf-8 -*-
"""
Проверка структуры DJVU файла с помощью djvudump
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
djvudump_path = r'C:\Program Files (x86)\DjVuLibre\djvudump.exe'

print(f"Checking structure of {djvu_path}...")

try:
    # Используем djvudump для проверки структуры
    result = subprocess.run(
        [djvudump_path, djvu_path],
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
        print(f"\nFirst 2000 characters of output:")
        print(result.stdout[:2000])
    else:
        print("No output from djvudump")

except Exception as e:
    print(f"Error: {e}")

print("Done")
