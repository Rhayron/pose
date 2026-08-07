"""
Gera os alvos ChArUco de POSE — os que vão colados no aparato, não o de calibração.

Diferença de propósito: o tabuleiro de calibração é grande, fica solto e é
manipulado pelo operador. Estes são pequenos, ficam fixos em faces distintas
do objeto rastreado, e cada um precisa ser identificável sozinho.

Três decisões, com o porquê:

* **Dicionário `DICT_4X4_100`, IDs a partir de 50.** Marcadores de 4x4 bits são
  os mais robustos a borrão e a alvo pequeno — menos bits para decodificar.
  Verificado que `DICT_4X4_50` é prefixo de `DICT_4X4_100`, então IDs >= 50 não
  colidem com o tabuleiro de calibração (que usa 0-16 do dicionário de 50).
  Também não colidem com o que já está no aparato (7x7 ID 0 e 5x5 ID 3).

* **Faixa de IDs distinta por face.** Um único detector reconhece todas e sabe
  qual face está vendo. Sem isso, duas faces iguais dariam poses ambíguas.

* **Faces múltiplas e não coplanares.** A análise dos vídeos de 27/05 mostrou o
  problema central do aparato atual: com um só marcador visível por quadro, a
  pose vem de 4 pontos coplanares — fraca em orientação e ambígua em
  profundidade. Duas faces em planos diferentes quebram a ambiguidade.

Uso:
    python gerar_alvos_pose.py
    python gerar_alvos_pose.py --faces 4 --pagina A4-paisagem
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import cv2
import numpy as np

from gerar_tabuleiro import PAGINAS_MM, svg_regua
from nucleo import agora, ambiente, dicionario_por_nome

DICIONARIO = "DICT_4X4_100"
ID_INICIAL = 50          # abaixo disso é território do tabuleiro de calibração

# nome, quadrados (x,y), lado do quadrado em mm, razão marcador/quadrado
MODELOS = [
    ("P", (3, 3), 10.0, 0.75),   # 30 x 30 mm, 4 cantos internos
    ("M", (4, 4), 12.0, 0.75),   # 48 x 48 mm, 9 cantos internos
]


def montar(faces: int):
    """Aloca faixas de IDs e constrói um board por face, sem sobreposição."""
    dic = dicionario_por_nome(DICIONARIO)
    proximo, alvos = ID_INICIAL, []
    for modelo, (sx, sy), quadrado, razao in MODELOS:
        for f in range(faces):
            n_marc = (sx * sy) // 2
            ids = np.arange(proximo, proximo + n_marc)
            proximo += n_marc
            marcador = round(quadrado * razao, 2)
            board = cv2.aruco.CharucoBoard((sx, sy), quadrado, marcador, dic, ids)
            alvos.append({
                "nome": f"{modelo}_{chr(65 + f)}",
                "board": board,
                "squares": [sx, sy],
                "square_mm": quadrado,
                "marker_mm": marcador,
                "ids": ids.tolist(),
                "cantos_internos": len(board.getChessboardCorners()),
                "largura_mm": sx * quadrado,
                "altura_mm": sy * quadrado,
            })
    if proximo > 100:
        raise SystemExit(f"[erro] {proximo - ID_INICIAL} IDs necessarios; "
                         f"{DICIONARIO} nao comporta. Reduza --faces.")
    return alvos


def alcance(marker_mm, fx_px=2900.0, px_min=25.0):
    """Distância máxima estimada para decodificar, em mm.

    px_min = 25 px por lado do marcador é a regra prática para decodificação
    confiável em água limpa. Sob turbidez, conte com metade da distância.
    fx provisório: a calibração em curso ainda tem IC 95% largo.
    """
    return marker_mm * fx_px / px_min


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--faces", type=int, default=3,
                    help="quantas faces distintas por tamanho (padrao 3)")
    ap.add_argument("--pagina", default="A4-paisagem", choices=sorted(PAGINAS_MM))
    ap.add_argument("--dpi", type=float, default=600.0,
                    help="alvos pequenos pedem mais resolucao que o tabuleiro grande")
    ap.add_argument("--saida", default="saida/alvos_pose")
    args = ap.parse_args()

    alvos = montar(args.faces)
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    px_mm = args.dpi / 25.4

    # --- raster de cada alvo ------------------------------------------------
    for a in alvos:
        tam = (int(round(a["largura_mm"] * px_mm)), int(round(a["altura_mm"] * px_mm)))
        img = a["board"].generateImage(tam, marginSize=0, borderBits=1)
        arq = saida / f"alvo_{a['nome']}.png"
        cv2.imwrite(str(arq), img)
        a["png"] = arq

    # --- folha para impressão ----------------------------------------------
    larg_pag, alt_pag = PAGINAS_MM[args.pagina]
    margem, gap, rot = 14.0, 12.0, 7.0
    partes, y = [], 16.0
    for modelo, _, _, _ in MODELOS:
        grupo = [a for a in alvos if a["nome"].startswith(modelo + "_")]
        x = margem
        for a in grupo:
            b64 = base64.b64encode(a["png"].read_bytes()).decode("ascii")
            partes.append(
                f'<rect x="{x-3}" y="{y-3}" width="{a["largura_mm"]+6}" '
                f'height="{a["altura_mm"]+6}" fill="none" stroke="#bbb" '
                f'stroke-width="0.2" stroke-dasharray="2 1"/>'
                f'<image x="{x}" y="{y}" width="{a["largura_mm"]}" height="{a["altura_mm"]}" '
                f'preserveAspectRatio="none" image-rendering="pixelated" '
                f'xlink:href="data:image/png;base64,{b64}"/>'
                f'<text x="{x}" y="{y + a["altura_mm"] + 6}" font-family="sans-serif" '
                f'font-size="2.8" fill="#000">{a["nome"]} · ids {a["ids"][0]}-{a["ids"][-1]} '
                f'· quad {a["square_mm"]:g} mm · {a["cantos_internos"]} cantos</text>')
            x += a["largura_mm"] + gap
        y += grupo[0]["altura_mm"] + rot + gap

    y_regua = y + 4
    textos = [
        f"ALVOS DE POSE · {DICIONARIO} · gerado {agora()}",
        "IMPRIMIR EM 100% / TAMANHO REAL. Conferir a regua de 100 mm e anotar o valor",
        "em escala_impressao_medida_mm no alvos_pose.json (vale para todos os alvos).",
        "Imprimir em fosco. Para uso submerso: laminar ou vinil adesivo; brilho gera",
        "reflexo especular que apaga os bits do marcador.",
    ]
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{larg_pag}mm" height="{alt_pag}mm" viewBox="0 0 {larg_pag} {alt_pag}">
  <rect width="{larg_pag}" height="{alt_pag}" fill="#fff"/>
  {''.join(partes)}
  {svg_regua(margem, y_regua)}
  {''.join(f'<text x="{margem}" y="{y_regua + 5 + 4.4*i}" font-family="sans-serif" font-size="3" fill="#000">{t}</text>' for i, t in enumerate(textos))}
</svg>
"""
    (saida / "folha_alvos.svg").write_text(svg, encoding="utf-8")

    # PDF: mesma máquina de escala exata do tabuleiro de calibração, para não
    # existirem dois caminhos diferentes de "imprimir em tamanho real"
    try:
        from PIL import Image, ImageDraw
        ppmm = args.dpi / 25.4
        pag = Image.new("RGB", (int(larg_pag * ppmm), int(alt_pag * ppmm)), "white")
        d = ImageDraw.Draw(pag)
        yy = 16.0
        for modelo, _, _, _ in MODELOS:
            grupo = [a for a in alvos if a["nome"].startswith(modelo + "_")]
            xx = margem
            for a in grupo:
                im = Image.open(a["png"]).convert("RGB").resize(
                    (int(a["largura_mm"] * ppmm), int(a["altura_mm"] * ppmm)), Image.NEAREST)
                pag.paste(im, (int(xx * ppmm), int(yy * ppmm)))
                xx += a["largura_mm"] + gap
            yy += grupo[0]["altura_mm"] + rot + gap
        from gerar_tabuleiro import _fonte
        f = _fonte(int(2.8 * ppmm))
        yy2 = 16.0
        for modelo, _, _, _ in MODELOS:
            grupo = [a for a in alvos if a["nome"].startswith(modelo + "_")]
            xx = margem
            for a in grupo:
                d.text((xx * ppmm, (yy2 + a["altura_mm"] + 3) * ppmm),
                       f"{a['nome']}  ids {a['ids'][0]}-{a['ids'][-1]}  quad {a['square_mm']:g}mm",
                       fill="black", font=f)
                xx += a["largura_mm"] + gap
            yy2 += grupo[0]["altura_mm"] + rot + gap
        d.line([(margem * ppmm, y_regua * ppmm), ((margem + 100) * ppmm, y_regua * ppmm)],
               fill="black", width=max(1, int(0.3 * ppmm)))
        for i in range(0, 101, 10):
            alt = (4.0 if i % 50 == 0 else 2.5) * ppmm
            d.line([((margem + i) * ppmm, y_regua * ppmm),
                    ((margem + i) * ppmm, y_regua * ppmm - alt)], fill="black",
                   width=max(1, int(0.3 * ppmm)))
        fg = _fonte(int(3 * ppmm))
        for i, t in enumerate(textos):
            d.text((margem * ppmm, (y_regua + 4 + 4.4 * i) * ppmm), t, fill="black", font=fg)
        pag.save(saida / "folha_alvos.pdf", "PDF", resolution=float(args.dpi))
        pdf_ok = True
    except ImportError:
        pdf_ok = False

    # --- manifesto ----------------------------------------------------------
    manifesto = {
        "dicionario": DICIONARIO,
        "escala_impressao_medida_mm": None,
        "nota_escala": ("meça a régua de 100 mm impressa e escreva aqui o valor real; "
                        "todos os alvos escalam pelo mesmo fator, pois saíram da mesma folha"),
        "alvos": [{k: v for k, v in a.items() if k not in ("board", "png")} for a in alvos],
        "alcance_estimado_mm": {a["nome"]: round(alcance(a["marker_mm"]), 0) for a in alvos},
        "premissas_alcance": {"fx_px": 2900.0, "px_min_por_marcador": 25.0,
                              "aviso": "fx provisório (IC 95% ainda largo); sob turbidez "
                                       "conte com metade da distância"},
        "geometria_entre_faces": None,
        "nota_geometria": ("depois de colar, MEDIR a transformação entre as faces e entre "
                           "cada face e o referencial do transdutor, e preencher aqui — "
                           "sem isso as poses das faces não podem ser combinadas"),
        "gerado_em": agora(),
        "ambiente": ambiente(),
    }
    (saida / "alvos_pose.json").write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n[ok] {len(alvos)} alvos em {saida.resolve()}\n")
    print(f"  {'alvo':6} {'ids':>10}  {'tamanho':>12}  {'cantos':>6}  alcance estimado")
    for a in alvos:
        print(f"  {a['nome']:6} {a['ids'][0]:3d}-{a['ids'][-1]:<3d}  "
              f"{a['largura_mm']:5.0f}x{a['altura_mm']:<5.0f} mm  {a['cantos_internos']:6d}  "
              f"ate ~{alcance(a['marker_mm'])/10:.0f} cm (agua limpa)")
    print(f"\n  folha_alvos.{'pdf' if pdf_ok else 'svg'}  <- IMPRIMIR em 100%")
    print("  alvos_pose.json  <- manifesto (detecção reconstrói os boards daqui)")
    print("""
PROXIMOS PASSOS
  1. Imprimir em fosco, 100%. Conferir a regua de 100 mm.
  2. Anotar o valor medido em 'escala_impressao_medida_mm'.
  3. Colar em faces NAO COPLANARES, em superficie rigida e plana.
  4. MEDIR a geometria entre as faces e ate o referencial do transdutor,
     e preencher 'geometria_entre_faces'. Sem isso cada face da uma pose
     isolada que nao pode ser combinada com as outras.
""")


def carregar(manifesto: str | Path):
    """Reconstrói os boards a partir do manifesto, para a detecção."""
    m = json.loads(Path(manifesto).read_text(encoding="utf-8"))
    dic = dicionario_por_nome(m["dicionario"])
    k = 1.0
    if m.get("escala_impressao_medida_mm"):
        k = m["escala_impressao_medida_mm"] / 100.0
    boards = {}
    for a in m["alvos"]:
        boards[a["nome"]] = cv2.aruco.CharucoBoard(
            tuple(a["squares"]), a["square_mm"] * k, a["marker_mm"] * k,
            dic, np.array(a["ids"]))
    return boards, m


if __name__ == "__main__":
    main()
