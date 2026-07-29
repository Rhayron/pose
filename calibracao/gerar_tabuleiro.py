"""
Gera o tabuleiro ChArUco imprimível + o contrato tabuleiro.json.

Saídas em saida/:
  tabuleiro.png  — raster 300 dpi (referência/backup)
  tabuleiro.svg  — VETOR com página em mm exatos  <- IMPRIMA ESTE
  tabuleiro.json — contrato lido por capturar.py e calibrar.py

Por que SVG: PNG não carrega escala física confiável entre visualizadores.
O SVG declara a página em mm, então "imprimir em 100% / tamanho real" sai
com a dimensão correta. Ainda assim a folha traz uma régua de 100 mm — a
impressora é um instrumento não calibrado e precisa ser verificada.

Uso:
    python gerar_tabuleiro.py
    python gerar_tabuleiro.py --squares 7 5 --quadrado-mm 35 --pagina A4-paisagem
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path

import cv2

from nucleo import ConfigTabuleiro, agora, construir_board

PAGINAS_MM = {
    "A4-paisagem": (297.0, 210.0),
    "A4-retrato": (210.0, 297.0),
    "A3-paisagem": (420.0, 297.0),
    "A3-retrato": (297.0, 420.0),
    "carta-paisagem": (279.4, 215.9),
}


def _fonte(px):
    from PIL import ImageFont
    for nome in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(nome, px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=px)     # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def salvar_pdf(destino, png, pagina_mm, board_mm, margem_lat, y_bd, dpi, textos,
               regua_mm=100.0):
    """PDF com página em tamanho físico exato — o formato certo para imprimir.

    O SVG depende de o visualizador respeitar as unidades; o PDF carrega a
    dimensão da página, então "100% / tamanho real" é inequívoco.
    """
    from PIL import Image, ImageDraw

    ppmm = dpi / 25.4
    larg_pag, alt_pag = (int(round(v * ppmm)) for v in pagina_mm)
    pagina = Image.new("RGB", (larg_pag, alt_pag), "white")
    tab = Image.open(png).convert("RGB").resize(
        (int(round(board_mm[0] * ppmm)), int(round(board_mm[1] * ppmm))), Image.NEAREST)
    pagina.paste(tab, (int(round(margem_lat * ppmm)), int(round(y_bd * ppmm))))

    d = ImageDraw.Draw(pagina)
    x0 = margem_lat * ppmm
    y_regua = (y_bd + board_mm[1] + 12.0) * ppmm
    d.line([(x0, y_regua), (x0 + regua_mm * ppmm, y_regua)], fill="black", width=max(1, int(0.3 * ppmm)))
    for i in range(0, int(regua_mm) + 1, 10):
        alt = (4.0 if i % 50 == 0 else 2.5) * ppmm
        d.line([(x0 + i * ppmm, y_regua), (x0 + i * ppmm, y_regua - alt)], fill="black",
               width=max(1, int(0.3 * ppmm)))
    fonte = _fonte(int(3.2 * ppmm))
    y = y_regua + 4.5 * ppmm
    for texto in textos:
        d.text((x0, y), texto, fill="black", font=fonte)
        y += 4.6 * ppmm
    pagina.save(destino, "PDF", resolution=float(dpi))


def svg_regua(x, y, comprimento_mm=100.0):
    partes = [
        '<g stroke="#000" stroke-width="0.3" fill="none">',
        f'<line x1="{x}" y1="{y}" x2="{x + comprimento_mm}" y2="{y}"/>',
    ]
    for i in range(0, int(comprimento_mm) + 1, 10):
        alt = 4.0 if i % 50 == 0 else 2.5
        partes.append(f'<line x1="{x + i}" y1="{y}" x2="{x + i}" y2="{y - alt}"/>')
    partes.append("</g>")
    partes.append(
        f'<text x="{x}" y="{y + 4.5}" font-family="sans-serif" font-size="3.2" fill="#000">'
        f"REGUA DE VERIFICACAO: esta linha deve medir exatamente 100,0 mm apos impressao"
        f"</text>"
    )
    return "\n".join(partes)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--squares", nargs=2, type=int, default=[7, 5], metavar=("X", "Y"))
    ap.add_argument("--quadrado-mm", type=float, default=35.0)
    ap.add_argument("--marcador-mm", type=float, default=None,
                    help="padrão: 0,75 x quadrado")
    ap.add_argument("--dicionario", default="DICT_4X4_50")
    ap.add_argument("--pagina", default="A4-paisagem", choices=sorted(PAGINAS_MM))
    ap.add_argument("--dpi", type=float, default=300.0)
    ap.add_argument("--saida", default="saida")
    args = ap.parse_args()

    sx, sy = args.squares
    quadrado = args.quadrado_mm
    marcador = args.marcador_mm if args.marcador_mm else round(0.75 * quadrado, 1)
    if not (0.4 * quadrado <= marcador < quadrado):
        raise SystemExit("[erro] marcador deve estar entre 0,4x e 1,0x o quadrado")

    larg_pag, alt_pag = PAGINAS_MM[args.pagina]
    larg_bd, alt_bd = sx * quadrado, sy * quadrado
    margem_lat = (larg_pag - larg_bd) / 2.0
    if margem_lat < 5 or alt_bd > alt_pag - 22:
        raise SystemExit(
            f"[erro] tabuleiro {larg_bd:.0f}x{alt_bd:.0f} mm não cabe em "
            f"{args.pagina} ({larg_pag:.0f}x{alt_pag:.0f} mm) com margem e régua.\n"
            f"       Reduza --quadrado-mm ou use uma página maior."
        )

    cfg = ConfigTabuleiro(
        dicionario=args.dicionario,
        squares_x=sx,
        squares_y=sy,
        square_mm_nominal=quadrado,
        marker_mm_nominal=marcador,
        square_mm_medido=None,
        gerado_em=agora(),
        opencv=cv2.__version__,
    )
    board, _ = construir_board(cfg, quadrado, marcador)

    px_por_mm = args.dpi / 25.4
    tam = (int(round(larg_bd * px_por_mm)), int(round(alt_bd * px_por_mm)))
    img = board.generateImage(tam, marginSize=0, borderBits=1)

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    png = saida / "tabuleiro.png"
    cv2.imwrite(str(png), img)

    textos = [
        f"ChArUco {sx}x{sy} | quadrado nominal {quadrado:g} mm | marcador {marcador:g} mm "
        f"| {args.dicionario} | {cfg.gerado_em}",
        "REGUA ACIMA = 100,0 mm. IMPRIMIR EM 100% / TAMANHO REAL (nunca \"ajustar a pagina\").",
        "Depois medir 5 quadrados com paquimetro, dividir por 5 e escrever em square_mm_medido",
        "no tabuleiro.json. Colar em superficie RIGIDA e PLANA antes de usar.",
    ]

    b64 = base64.b64encode(png.read_bytes()).decode("ascii")
    y_bd = 8.0
    y_regua = y_bd + alt_bd + 12.0
    y_txt = y_regua + 9.0
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{larg_pag}mm" height="{alt_pag}mm" viewBox="0 0 {larg_pag} {alt_pag}">
  <rect width="{larg_pag}" height="{alt_pag}" fill="#fff"/>
  <image x="{margem_lat}" y="{y_bd}" width="{larg_bd}" height="{alt_bd}"
         preserveAspectRatio="none" image-rendering="pixelated"
         xlink:href="data:image/png;base64,{b64}"/>
  {svg_regua(margem_lat, y_regua)}
  <text x="{margem_lat}" y="{y_txt}" font-family="sans-serif" font-size="3.2" fill="#000">
    ChArUco {sx}x{sy} | quadrado nominal {quadrado:g} mm | marcador {marcador:g} mm | {args.dicionario} | {cfg.gerado_em}
  </text>
  <text x="{margem_lat}" y="{y_txt + 4.5}" font-family="sans-serif" font-size="3.2" fill="#000">
    IMPRIMIR EM 100% / TAMANHO REAL (nunca "ajustar a pagina"). Depois medir 1 quadrado com paquimetro
  </text>
  <text x="{margem_lat}" y="{y_txt + 9.0}" font-family="sans-serif" font-size="3.2" fill="#000">
    e escrever o valor em square_mm_medido no tabuleiro.json. Colar em superficie RIGIDA e PLANA.
  </text>
</svg>
"""
    (saida / "tabuleiro.svg").write_text(svg, encoding="utf-8")

    pdf = saida / "tabuleiro.pdf"
    try:
        salvar_pdf(pdf, png, (larg_pag, alt_pag), (larg_bd, alt_bd), margem_lat,
                   y_bd, args.dpi, textos)
        aviso_pdf = f"  tabuleiro.pdf   <- IMPRIMA ESTE ({args.pagina}, 100% / tamanho real)"
    except ImportError:
        pdf = None
        aviso_pdf = ("  (PDF não gerado: Pillow ausente. `pip install pillow` para tê-lo;\n"
                     "   sem ele, imprima o SVG — só confira a régua com mais cuidado.)")

    cfg_path = saida / "tabuleiro.json"
    cfg.salvar(cfg_path)

    n_cantos = (sx - 1) * (sy - 1)
    print(f"""
[ok] Tabuleiro gerado em {saida.resolve()}

{aviso_pdf}
  tabuleiro.svg   alternativa vetorial ({args.pagina})
  tabuleiro.png   raster {tam[0]}x{tam[1]} px @ {args.dpi:g} dpi
  tabuleiro.json  contrato ({n_cantos} cantos internos, {sx}x{sy} quadrados)
  tabuleiro {larg_bd:g}x{alt_bd:g} mm em página {larg_pag:g}x{alt_pag:g} mm

PRÓXIMOS PASSOS (nesta ordem — a escala métrica do projeto depende disso):
  1. Imprimir o PDF em 100% / tamanho real (desligar "ajustar à página").
     Conferir a régua impressa: 100,0 mm com paquímetro ou régua de aço.
  2. Colar em superfície RÍGIDA e PLANA (vidro, MDF, placa de PVC). Papel ondulado
     vira erro sistemático de distorção que a calibração não distingue da lente.
  3. Medir um quadrado (melhor: medir 5 quadrados e dividir por 5) e escrever o
     valor em 'square_mm_medido' dentro de {cfg_path}.
  4. python capturar.py
""")


if __name__ == "__main__":
    main()
