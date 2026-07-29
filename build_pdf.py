# -*- coding: utf-8 -*-
"""Renderiza o roteiro (Markdown) em PDF: capa + um slide por pagina."""
import re
from fpdf import FPDF

SRC = r"C:\Users\Rhayron\Projects\pose\roteiro_apresentacao_completo.md"
OUT = r"C:\Users\Rhayron\Projects\pose\roteiro_apresentacao_completo.pdf"

FONTS = r"C:\Windows\Fonts"

# --- parse markdown -----------------------------------------------------
slides = []          # list of (title, [paragraphs])
with open(SRC, encoding="utf-8") as f:
    raw = f.read()

blocks = raw.split("\n")
cur_title = None
cur_paras = []
buf = []

def flush_para():
    if buf:
        cur_paras.append(" ".join(buf).strip())
        buf.clear()

for line in blocks:
    if line.startswith("## "):
        # start of a slide
        flush_para()
        if cur_title is not None:
            slides.append((cur_title, cur_paras))
        cur_title = line[3:].strip()
        cur_paras = []
    elif line.startswith("# "):
        continue  # doc title, handled by cover
    elif line.strip() == "":
        flush_para()
    else:
        buf.append(line.strip())
flush_para()
if cur_title is not None:
    slides.append((cur_title, cur_paras))

# --- pdf ----------------------------------------------------------------
ACCENT = (11, 79, 108)      # deep teal-blue
DARK = (33, 37, 41)
GREY = (110, 116, 122)

class PDF(FPDF):
    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-15)
        self.set_font("Georgia", "I", 8)
        self.set_text_color(*GREY)
        self.cell(0, 8, f"Roteiro de apresentação  ·  pág. {self.page_no() - 1}",
                  align="C")

pdf = PDF(format="A4")
pdf.set_auto_page_break(auto=True, margin=20)
pdf.set_margins(left=22, top=20, right=22)

pdf.add_font("Georgia", "", f"{FONTS}\\georgia.ttf")
pdf.add_font("Georgia", "B", f"{FONTS}\\georgiab.ttf")
pdf.add_font("Georgia", "I", f"{FONTS}\\georgiai.ttf")
pdf.add_font("Georgia", "BI", f"{FONTS}\\georgiaz.ttf")

# ---- cover -------------------------------------------------------------
pdf.add_page()
pdf.ln(30)
pdf.set_draw_color(*ACCENT)
pdf.set_line_width(0.8)
pdf.line(22, pdf.get_y(), 60, pdf.get_y())
pdf.ln(10)

pdf.set_font("Georgia", "B", 24)
pdf.set_text_color(*ACCENT)
pdf.multi_cell(0, 12, "Roteiro de Apresentação", align="L")
pdf.ln(2)
pdf.set_font("Georgia", "I", 13)
pdf.set_text_color(*GREY)
pdf.multi_cell(0, 7, "Versão com falas complementadas e autossuficientes", align="L")
pdf.ln(12)

pdf.set_font("Georgia", "B", 14)
pdf.set_text_color(*DARK)
pdf.multi_cell(0, 8,
    "Estimação visual de pose 6DoF de um transdutor ultrassônico e "
    "registro espacial 3D de imagens de ultrassom para inspeção "
    "subaquática por ensaios não destrutivos", align="L")
pdf.ln(14)

pdf.set_font("Georgia", "", 12)
pdf.set_text_color(*DARK)
info = [
    ("Autor", "Rhayron de Sousa Nogueira"),
    ("Orientador", "Prof. Thiago Passarin"),
    ("Programa", "CPGEI - UTFPR  |  Laboratório LASSIP"),
    ("Documento", "Delineamento de pesquisa de mestrado"),
]
label_w = 34
val_x = 22 + label_w
val_w = pdf.w - 22 - val_x
for k, v in info:
    y = pdf.get_y()
    pdf.set_xy(22, y)
    pdf.set_font("Georgia", "B", 12)
    pdf.set_text_color(*ACCENT)
    pdf.cell(label_w, 8, k, new_x="RIGHT", new_y="TOP")
    pdf.set_font("Georgia", "", 12)
    pdf.set_text_color(*DARK)
    pdf.set_xy(val_x, y)
    pdf.multi_cell(val_w, 8, v, align="L", new_x="LMARGIN", new_y="NEXT")

pdf.ln(16)
pdf.set_draw_color(220, 224, 228)
pdf.set_line_width(0.3)
pdf.line(22, pdf.get_y(), pdf.w - 22, pdf.get_y())
pdf.ln(4)
pdf.set_font("Georgia", "I", 9.5)
pdf.set_text_color(*GREY)
pdf.multi_cell(0, 5.5,
    "Nesta versão, cada termo técnico (PnP, RANSAC, ArUco, ChArUco, PVNet, "
    "TFM, CPWC, FMC, NTU, ground truth, adaptação de domínio, entre outros) "
    "é explicado na primeira vez em que aparece, de modo que o roteiro possa "
    "ser lido e apresentado sem depender de conhecimento prévio.", align="L")

# ---- slides ------------------------------------------------------------
for title, paras in slides:
    pdf.add_page()
    # slide label / number
    m = re.match(r"Slide (\d+)\.\s*(.*)", title)
    if m:
        num, name = m.group(1), m.group(2)
    else:
        num, name = "", title

    pdf.set_font("Georgia", "B", 10)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 6, f"SLIDE {num}".strip(), align="L")
    pdf.ln(7)
    pdf.set_font("Georgia", "B", 16)
    pdf.set_text_color(*DARK)
    pdf.multi_cell(0, 8, name, align="L")
    pdf.ln(1)
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.6)
    pdf.line(22, pdf.get_y(), pdf.w - 22, pdf.get_y())
    pdf.ln(5)

    pdf.set_font("Georgia", "", 11.5)
    pdf.set_text_color(*DARK)
    for p in paras:
        pdf.multi_cell(0, 6.4, p, align="J")
        pdf.ln(3)

pdf.output(OUT)
print("OK ->", OUT)
print("slides:", len(slides))
