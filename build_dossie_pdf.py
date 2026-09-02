# -*- coding: utf-8 -*-
"""Renderiza o dossiê (dossie_projeto.md) em PDF.

Portável: usa Georgia no Windows e DejaVu Serif no Linux. Suporta o subconjunto
de Markdown que o dossiê usa — títulos ##, parágrafos, listas com hífen,
tabelas de pipe e blocos de código cercados.

    python build_dossie_pdf.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

RAIZ = Path(__file__).resolve().parent
SRC = RAIZ / "dossie_projeto.md"
OUT = RAIZ / "dossie_projeto.pdf"

ACCENT = (11, 79, 108)
DARK = (33, 37, 41)
GREY = (110, 116, 122)
LINE = (220, 224, 228)


def achar_fontes() -> dict[str, str]:
    """Georgia no Windows, DejaVu Serif fora dele; mono sempre DejaVu/Consolas."""
    candidatos = [
        {  # Windows
            "": r"C:\Windows\Fonts\georgia.ttf",
            "B": r"C:\Windows\Fonts\georgiab.ttf",
            "I": r"C:\Windows\Fonts\georgiai.ttf",
            "BI": r"C:\Windows\Fonts\georgiaz.ttf",
            "mono": r"C:\Windows\Fonts\consola.ttf",
        },
        {  # Linux (Arch/Debian)
            "": "/usr/share/fonts/TTF/DejaVuSerif.ttf",
            "B": "/usr/share/fonts/TTF/DejaVuSerif-Bold.ttf",
            "I": "/usr/share/fonts/TTF/DejaVuSerif-Italic.ttf",
            "BI": "/usr/share/fonts/TTF/DejaVuSerif-BoldItalic.ttf",
            "mono": "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        },
        {
            "": "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "B": "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "I": "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
            "BI": "/usr/share/fonts/truetype/dejavu/DejaVuSerif-BoldItalic.ttf",
            "mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        },
    ]
    for conjunto in candidatos:
        if all(Path(p).exists() for p in conjunto.values()):
            return conjunto
    sys.exit("nenhum conjunto de fontes encontrado (Georgia ou DejaVu Serif)")


# --- parse do markdown ---------------------------------------------------

def parse(texto: str) -> tuple[str, str, list[dict]]:
    """Devolve (título, subtítulo, blocos). Bloco: heading, para, bullet, table, code."""
    linhas = texto.split("\n")
    titulo, subtitulo = "", ""
    blocos: list[dict] = []
    buf: list[str] = []
    i = 0

    def flush() -> None:
        if buf:
            blocos.append({"tipo": "para", "texto": " ".join(buf).strip()})
            buf.clear()

    # título = primeiro '# '; subtítulo = primeiro parágrafo após ele
    while i < len(linhas):
        linha = linhas[i]
        if linha.startswith("# ") and not titulo:
            titulo = linha[2:].strip()
            i += 1
            while i < len(linhas) and not linhas[i].strip():
                i += 1
            sub: list[str] = []
            while i < len(linhas) and linhas[i].strip() and not linhas[i].startswith("#"):
                sub.append(linhas[i].strip())
                i += 1
            subtitulo = " ".join(sub)
            continue
        if linha.startswith("## "):
            flush()
            blocos.append({"tipo": "heading", "texto": linha[3:].strip()})
        elif linha.startswith("```"):
            flush()
            codigo: list[str] = []
            i += 1
            while i < len(linhas) and not linhas[i].startswith("```"):
                codigo.append(linhas[i])
                i += 1
            blocos.append({"tipo": "code", "linhas": codigo})
        elif linha.startswith("|"):
            flush()
            tabela: list[list[str]] = []
            while i < len(linhas) and linhas[i].startswith("|"):
                celulas = [c.strip() for c in linhas[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in celulas):
                    tabela.append(celulas)
                i += 1
            blocos.append({"tipo": "table", "linhas": tabela})
            continue
        elif linha.startswith("- "):
            flush()
            item = [linha[2:].strip()]
            while i + 1 < len(linhas) and linhas[i + 1].startswith("  ") \
                    and linhas[i + 1].strip() and not linhas[i + 1].startswith("- "):
                i += 1
                item.append(linhas[i].strip())
            blocos.append({"tipo": "bullet", "texto": " ".join(item)})
        elif not linha.strip():
            flush()
        else:
            buf.append(linha.strip())
        i += 1
    flush()
    return titulo, subtitulo, blocos


def limpar(texto: str) -> str:
    """Remove ênfase de markdown e crases; o PDF usa tipografia, não marcação."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)
    texto = re.sub(r"\*(.+?)\*", r"\1", texto)
    return texto.replace("`", "")


# --- pdf -----------------------------------------------------------------

class DossiePDF(FPDF):
    def footer(self) -> None:
        if self.page_no() == 1:
            return
        self.set_y(-15)
        self.set_font("Serif", "I", 8)
        self.set_text_color(*GREY)
        self.cell(0, 8, f"Dossiê do projeto pose  ·  pág. {self.page_no() - 1}",
                  align="C")


def montar(titulo: str, subtitulo: str, blocos: list[dict]) -> FPDF:
    fontes = achar_fontes()
    pdf = DossiePDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(left=22, top=20, right=22)
    for estilo in ("", "B", "I", "BI"):
        pdf.add_font("Serif", estilo, fontes[estilo])
    pdf.add_font("Mono", "", fontes["mono"])

    # capa
    pdf.add_page()
    pdf.ln(30)
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(22, pdf.get_y(), 60, pdf.get_y())
    pdf.ln(10)
    pdf.set_font("Serif", "B", 24)
    pdf.set_text_color(*ACCENT)
    pdf.multi_cell(0, 12, titulo, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(6)
    pdf.set_font("Serif", "", 12.5)
    pdf.set_text_color(*DARK)
    pdf.multi_cell(0, 7, limpar(subtitulo), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(14)
    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.3)
    pdf.line(22, pdf.get_y(), pdf.w - 22, pdf.get_y())

    for bloco in blocos:
        tipo = bloco["tipo"]
        if tipo == "heading":
            pdf.add_page()
            pdf.set_font("Serif", "B", 16)
            pdf.set_text_color(*DARK)
            pdf.multi_cell(0, 8, limpar(bloco["texto"]), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1)
            pdf.set_draw_color(*ACCENT)
            pdf.set_line_width(0.6)
            pdf.line(22, pdf.get_y(), pdf.w - 22, pdf.get_y())
            pdf.ln(5)
        elif tipo == "para":
            pdf.set_font("Serif", "", 11)
            pdf.set_text_color(*DARK)
            pdf.multi_cell(0, 6.2, limpar(bloco["texto"]), align="J", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(3)
        elif tipo == "bullet":
            pdf.set_font("Serif", "", 11)
            pdf.set_text_color(*DARK)
            x = pdf.get_x()
            pdf.cell(6, 6.2, "–")
            pdf.multi_cell(pdf.w - pdf.r_margin - x - 6, 6.2,
                           limpar(bloco["texto"]), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(1.5)
        elif tipo == "code":
            pdf.set_font("Mono", "", 8.2)
            pdf.set_text_color(*DARK)
            pdf.set_fill_color(246, 247, 248)
            for linha in bloco["linhas"]:
                pdf.multi_cell(0, 4.6, linha if linha.strip() else " ",
                               align="L", fill=True,
                               new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(3)
        elif tipo == "table":
            linhas = [[limpar(c) for c in row] for row in bloco["linhas"]]
            if not linhas:
                continue
            pdf.set_font("Serif", "", 9)
            pdf.set_text_color(*DARK)
            pdf.set_draw_color(*LINE)
            pdf.set_line_width(0.2)
            with pdf.table(
                first_row_as_headings=True,
                line_height=5.4,
                padding=1.6,
            ) as tabela:
                for r, row in enumerate(linhas):
                    linha_pdf = tabela.row()
                    for celula in row:
                        if r == 0:
                            pdf.set_font("Serif", "B", 9)
                        else:
                            pdf.set_font("Serif", "", 9)
                        linha_pdf.cell(celula)
            pdf.ln(4)
    return pdf


def main() -> None:
    titulo, subtitulo, blocos = parse(SRC.read_text(encoding="utf-8"))
    pdf = montar(titulo, subtitulo, blocos)
    pdf.output(str(OUT))
    print("OK ->", OUT)


if __name__ == "__main__":
    main()
