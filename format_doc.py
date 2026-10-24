import sys
sys.stdout.reconfigure(encoding='utf-8')

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import re

# Load both documents
doc1 = Document(r'C:\Users\light\Documents\ИП\Рамочный договор на разработку ПО.docx')
doc2 = Document(r'C:\Users\light\Documents\ИП\Рамочный договор на разработку ПО (ИП — ООО).docx')

# Create new document based on doc2's structure
new_doc = Document()

# Copy page setup from doc2
for i, section in enumerate(new_doc.sections):
    if i < len(doc2.sections):
        src_section = doc2.sections[i]
        section.page_width = src_section.page_width
        section.page_height = src_section.page_height
        section.left_margin = src_section.left_margin
        section.right_margin = src_section.right_margin
        section.top_margin = src_section.top_margin
        section.bottom_margin = src_section.bottom_margin

# Helper to set paragraph style and formatting
def apply_style(paragraph, style_name):
    paragraph.style = new_doc.styles[style_name]

def set_run_formatting(run, bold=None, italic=None, underline=None, font_name=None, font_size=None, color=None):
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if underline is not None:
        run.underline = underline
    if font_name is not None:
        run.font.name = font_name
    if font_size is not None:
        run.font.size = Pt(font_size)
    if color is not None:
        run.font.color.rgb = RGBColor(*color)

# Process doc1 content and map to doc2 structure
# We'll create a new document with doc2's structure but doc1's content where applicable

# Title - use doc1's title with Heading 1 style
title_para = new_doc.add_paragraph(doc1.paragraphs[0].text)
apply_style(title_para, 'Heading 1')

# Preamble paragraphs (0-5 in doc1) - use Normal style
for i in range(1, 6):
    p = new_doc.add_paragraph(doc1.paragraphs[i].text)
    apply_style(p, 'Normal')

# Empty line
new_doc.add_paragraph('')

# Section 1: Предмет договора и основные понятия
h = new_doc.add_paragraph('1. Предмет договора и основные понятия')
apply_style(h, 'Heading 2')

# 1.1
p = new_doc.add_paragraph('1.1. Настоящий Договор является рамочным (п. 1 ст. 429.1 ГК РФ). Исполнитель обязуется по заданию Заказчика оказывать услуги по разработке, доработке, адаптации под бизнес-процессы Заказчика и техническому сопровождению программного обеспечения, исключительные права на которое принадлежат Исполнителю (далее — «ПО»), а Заказчик обязуется принимать и оплачивать эти услуги.')
apply_style(p, 'Normal')

# 1.2
p = new_doc.add_paragraph('1.2. Конкретный объём, содержание, срок и стоимость услуг согласуются Сторонами в отдельных Заявках (далее — «Заказ»), оформляемых по форме Приложения № 1. Каждый подписанный Заказ является неотъемлемой частью Договора.')
apply_style(p, 'Normal')

# 1.3
p = new_doc.add_paragraph('1.3. ' + doc1.paragraphs[11].text)
apply_style(p, 'Normal')

# 1.4
p = new_doc.add_paragraph('1.4. ' + doc1.paragraphs[12].text.replace('главы 39', 'главы 37 ГК РФ (подряд) и, в части оказания услуг, главы 39'))
apply_style(p, 'Normal')

# 1.5
p = new_doc.add_paragraph('1.5. В Договоре используются следующие понятия:')
apply_style(p, 'Normal')

# Definitions - List Paragraph style
definitions = [
    ('ПО', doc1.paragraphs[14].text.replace('ПО — ', '')),
    ('Работы', doc1.paragraphs[15].text.replace('Работы — ', '')),
    ('Доступ', doc1.paragraphs[16].text.replace('Доступ — ', '')),
    ('Техническое задание (ТЗ)', doc1.paragraphs[17].text.replace('Техническое задание (ТЗ) — ', '')),
    ('Этап', doc1.paragraphs[18].text.replace('Этап — ', '')),
    ('Акт', doc1.paragraphs[19].text.replace('Акт — ', '')),
]

for term, defn in definitions:
    p = new_doc.add_paragraph(f'{term} — {defn}')
    apply_style(p, 'List Paragraph')

# Section 2: Порядок оформления Заказов
h = new_doc.add_paragraph('2. Порядок оформления Заказов')
apply_style(h, 'Heading 2')

# 2.1
p = new_doc.add_paragraph('2.1. ' + doc1.paragraphs[22].text)
apply_style(p, 'Normal')

# 2.2
p = new_doc.add_paragraph('2.2. Заказ должен содержать:')
apply_style(p, 'Normal')

order_items = [
    doc1.paragraphs[24].text.replace('- ', ''),
    doc1.paragraphs[25].text.replace('- ', ''),
    doc1.paragraphs[26].text.replace('- ', ''),
    doc1.paragraphs[27].text.replace('- ', ''),
    doc1.paragraphs[28].text.replace('- ', ''),
    doc1.paragraphs[29].text.replace('- ', ''),
]

for item in order_items:
    p = new_doc.add_paragraph(item)
    apply_style(p, 'List Paragraph')

# 2.3
p = new_doc.add_paragraph('2.3. ' + doc1.paragraphs[30].text)
apply_style(p, 'Normal')

# 2.4
p = new_doc.add_paragraph('2.4. ' + doc1.paragraphs[31].text)
apply_style(p, 'Normal')

# 2.5
p = new_doc.add_paragraph('2.5. ' + doc1.paragraphs[32].text)
apply_style(p, 'Normal')

# 2.6
p = new_doc.add_paragraph('2.6. ' + doc1.paragraphs[33].text)
apply_style(p, 'Normal')

# Section 3: Права и обязанности Сторон
h = new_doc.add_paragraph('3. Права и обязанности Сторон')
apply_style(h, 'Heading 2')

# 3.1
p = new_doc.add_paragraph('3.1. Исполнитель обязуется:')
apply_style(p, 'Normal')

exec_obligations = [
    doc1.paragraphs[36].text.replace('- ', ''),
    doc1.paragraphs[37].text.replace('- ', ''),
    doc1.paragraphs[38].text.replace('- ', ''),
    doc1.paragraphs[39].text.replace('- ', ''),
    doc1.paragraphs[40].text.replace('- ', ''),
    doc1.paragraphs[41].text.replace('- ', ''),
    doc1.paragraphs[42].text.replace('- ', ''),
]

for item in exec_obligations:
    p = new_doc.add_paragraph(item)
    apply_style(p, 'List Paragraph')

# 3.2
p = new_doc.add_paragraph('3.2. Исполнитель вправе:')
apply_style(p, 'Normal')

exec_rights = [
    doc1.paragraphs[44].text.replace('- ', ''),
    doc1.paragraphs[45].text.replace('- ', ''),
    doc1.paragraphs[46].text.replace('- ', ''),
    doc1.paragraphs[47].text.replace('- ', ''),
    doc1.paragraphs[48].text.replace('- ', ''),
]

for item in exec_rights:
    p = new_doc.add_paragraph(item)
    apply_style(p, 'List Paragraph')

# 3.3
p = new_doc.add_paragraph('3.3. Заказчик обязуется:')
apply_style(p, 'Normal')

client_obligations = [
    doc1.paragraphs[50].text.replace('- ', ''),
    doc1.paragraphs[51].text.replace('- ', ''),
    doc1.paragraphs[52].text.replace('- ', ''),
    doc1.paragraphs[53].text.replace('- ', ''),
    doc1.paragraphs[54].text.replace('- ', ''),
]

for item in client_obligations:
    p = new_doc.add_paragraph(item)
    apply_style(p, 'List Paragraph')

# 3.4
p = new_doc.add_paragraph('3.4. ' + doc1.paragraphs[56].text)
apply_style(p, 'Normal')

# 3.5
p = new_doc.add_paragraph('3.5. ' + doc1.paragraphs[58].text.replace('Статус Сторон\n', ''))
apply_style(p, 'Normal')

# Section 4: Сроки, сдача-приёмка и гарантия
h = new_doc.add_paragraph('4. Сроки, сдача-приёмка и гарантия')
apply_style(h, 'Heading 2')

for i in range(60, 67):
    p = new_doc.add_paragraph(doc1.paragraphs[i].text)
    apply_style(p, 'Normal')

# Section 5: Стоимость и порядок расчётов
h = new_doc.add_paragraph('5. Стоимость и порядок расчётов')
apply_style(h, 'Heading 2')

for i in range(68, 79):
    text = doc1.paragraphs[i].text
    if text.strip().startswith('- '):
        p = new_doc.add_paragraph(text.replace('- ', ''))
        apply_style(p, 'List Paragraph')
    else:
        p = new_doc.add_paragraph(text)
        apply_style(p, 'Normal')

# Section 6: Интеллектуальные права (keep doc1 content but with doc2 formatting)
h = new_doc.add_paragraph('6. Интеллектуальные права')
apply_style(h, 'Heading 2')

for i in range(80, 88):
    p = new_doc.add_paragraph(doc1.paragraphs[i].text)
    apply_style(p, 'Normal')

# Section 7: Конфиденциальность
h = new_doc.add_paragraph('7. Конфиденциальность')
apply_style(h, 'Heading 2')

for i in range(89, 94):
    p = new_doc.add_paragraph(doc1.paragraphs[i].text)
    apply_style(p, 'Normal')

# Section 8: Ответственность
h = new_doc.add_paragraph('8. Ответственность')
apply_style(h, 'Heading 2')

for i in range(95, 101):
    p = new_doc.add_paragraph(doc1.paragraphs[i].text)
    apply_style(p, 'Normal')

# Section 9: Обстоятельства непреодолимой силы
h = new_doc.add_paragraph('9. Обстоятельства непреодолимой силы')
apply_style(h, 'Heading 2')

for i in range(102, 104):
    p = new_doc.add_paragraph(doc1.paragraphs[i].text)
    apply_style(p, 'Normal')

# Section 10: Срок действия и прекращение Договора
h = new_doc.add_paragraph('10. Срок действия и прекращение Договора')
apply_style(h, 'Heading 2')

for i in range(105, 110):
    p = new_doc.add_paragraph(doc1.paragraphs[i].text)
    apply_style(p, 'Normal')

# Section 11: Порядок разрешения споров
h = new_doc.add_paragraph('11. Порядок разрешения споров')
apply_style(h, 'Heading 2')

for i in range(111, 114):
    p = new_doc.add_paragraph(doc1.paragraphs[i].text)
    apply_style(p, 'Normal')

# Section 12: Прочие условия, реквизиты и подписи
h = new_doc.add_paragraph('12. Прочие условия, реквизиты и подписи')
apply_style(h, 'Heading 2')

for i in range(115, 120):
    p = new_doc.add_paragraph(doc1.paragraphs[i].text)
    apply_style(p, 'Normal')

# 12.6
p = new_doc.add_paragraph('12.6. Реквизиты и подписи Сторон')
apply_style(p, 'Normal')

# Empty paragraphs for signatures
for _ in range(4):
    new_doc.add_paragraph('')

# Приложение № 1
h = new_doc.add_paragraph('Приложение № 1. Форма Заказа (дополнительного соглашения)')
apply_style(h, 'Heading 2')

# Process appendix 1 content
app1_start = 124
for i in range(app1_start + 1, 138):  # Skip the heading at 124
    text = doc1.paragraphs[i].text
    if not text.strip():
        new_doc.add_paragraph('')
        continue
    style = doc1.paragraphs[i].style.name
    if style == 'List Paragraph':
        p = new_doc.add_paragraph(text)
        apply_style(p, 'List Paragraph')
    elif style == 'Heading 2':
        # Skip duplicate heading
        continue
    else:
        p = new_doc.add_paragraph(text)
        apply_style(p, 'Normal')

# Приложение № 2
h = new_doc.add_paragraph('Приложение № 2. Форма Акта сдачи-приёмки')
apply_style(h, 'Heading 2')

app2_start = 154
for i in range(app2_start + 1, 163):  # Skip the heading at 154
    text = doc1.paragraphs[i].text
    if not text.strip():
        new_doc.add_paragraph('')
        continue
    style = doc1.paragraphs[i].style.name
    if style == 'Heading 2':
        # Skip duplicate heading
        continue
    else:
        p = new_doc.add_paragraph(text)
        apply_style(p, 'Normal')

# Save
output_path = r'C:\Users\light\Documents\ИП\Рамочный договор на разработку ПО1.docx'
new_doc.save(output_path)
print(f'Saved to: {output_path}')
print(f'Total paragraphs: {len(new_doc.paragraphs)}')