from docx import Document
from docx.shared import Pt, Cm, RGBColor
import json

def extract_doc_info(path):
    doc = Document(path)
    info = {
        'paragraphs': [],
        'styles': {},
        'sections': []
    }
    
    for i, p in enumerate(doc.paragraphs):
        runs_info = []
        for r in p.runs:
            runs_info.append({
                'text': r.text,
                'bold': r.bold,
                'italic': r.italic,
                'underline': r.underline,
                'font_name': r.font.name,
                'font_size': r.font.size.pt if r.font.size else None,
                'font_color': str(r.font.color.rgb) if r.font.color and r.font.color.rgb else None
            })
        info['paragraphs'].append({
            'index': i,
            'text': p.text,
            'style': p.style.name,
            'alignment': str(p.alignment) if p.alignment else None,
            'runs': runs_info
        })
    
    for section in doc.sections:
        info['sections'].append({
            'page_width': section.page_width.cm if section.page_width else None,
            'page_height': section.page_height.cm if section.page_height else None,
            'left_margin': section.left_margin.cm if section.left_margin else None,
            'right_margin': section.right_margin.cm if section.right_margin else None,
            'top_margin': section.top_margin.cm if section.top_margin else None,
            'bottom_margin': section.bottom_margin.cm if section.bottom_margin else None
        })
    
    for style in doc.styles:
        if style.type == 1:  # Paragraph style
            info['styles'][style.name] = {
                'font_name': style.font.name,
                'font_size': style.font.size.pt if style.font.size else None,
                'bold': style.font.bold,
                'italic': style.font.italic,
                'space_before': style.paragraph_format.space_before.pt if style.paragraph_format.space_before else None,
                'space_after': style.paragraph_format.space_after.pt if style.paragraph_format.space_after else None,
                'line_spacing': style.paragraph_format.line_spacing
            }
    
    return info

# Extract both documents
doc1 = extract_doc_info(r'C:\Users\light\Documents\ИП\Рамочный договор на разработку ПО.docx')
doc2 = extract_doc_info(r'C:\Users\light\Documents\ИП\Рамочный договор на разработку ПО (ИП — ООО).docx')

import sys
sys.stdout.reconfigure(encoding='utf-8')

print('=== DOC 1 (Source) ===')
print(f'Paragraphs: {len(doc1["paragraphs"])}')
print(f'Sections: {len(doc1["sections"])}')
print(f'Styles: {len(doc1["styles"])}')
print()
print('First 15 paragraphs:')
for p in doc1['paragraphs'][:15]:
    print(f'  [{p["style"]}] {p["text"][:100]}')

print()
print('=== DOC 2 (Template) ===')
print(f'Paragraphs: {len(doc2["paragraphs"])}')
print(f'Sections: {len(doc2["sections"])}')
print(f'Styles: {len(doc2["styles"])}')
print()
print('First 15 paragraphs:')
for p in doc2['paragraphs'][:15]:
    print(f'  [{p["style"]}] {p["text"][:100]}')

print()
print('=== DOC 2 Sections ===')
for i, s in enumerate(doc2['sections']):
    print(f'  Section {i}: {s}')

print()
print('=== DOC 2 Key Styles ===')
for name, s in doc2['styles'].items():
    if any(k in name.lower() for k in ['heading', 'normal', 'title', 'list', 'toc', 'caption']):
        print(f'  {name}: {s}')

# Save full info for later use
with open('doc1_info.json', 'w', encoding='utf-8') as f:
    json.dump(doc1, f, ensure_ascii=False, indent=2, default=str)
with open('doc2_info.json', 'w', encoding='utf-8') as f:
    json.dump(doc2, f, ensure_ascii=False, indent=2, default=str)