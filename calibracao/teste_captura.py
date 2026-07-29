"""
Teste sem GUI do núcleo de captura (`captura_core.SessaoCaptura`).

A GUI e a CLI dependem exatamente destas decisões — aceitar/recusar um quadro,
contar bins, retomar sessão, desfazer. Como a janela não pode ser testada
automaticamente, o que dá para testar é testado aqui, com quadros sintéticos.

    python teste_captura.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from captura_core import SessaoCaptura, desenhar_overlay
from nucleo import ConfigTabuleiro, construir_board, novo_detector
from teste_sintetico import GT_DIST, GT_K, GT_QUADRADO_MM, GT_RES, gerar_poses, renderizar

falhas = []


def checar(nome, condicao, detalhe=""):
    print(f"  {'OK  ' if condicao else 'FALHA'} {nome}   {detalhe}")
    if not condicao:
        falhas.append(nome)


def main():
    rng = np.random.default_rng(7)
    tmp = Path(tempfile.mkdtemp(prefix="teste_captura_"))
    cfg = ConfigTabuleiro(square_mm_nominal=GT_QUADRADO_MM,
                          marker_mm_nominal=round(0.75 * GT_QUADRADO_MM, 1))
    board, _ = construir_board(cfg, GT_QUADRADO_MM, cfg.marker_mm_nominal)
    detector = novo_detector(board)

    largura_mm = cfg.squares_x * GT_QUADRADO_MM
    altura_mm = cfg.squares_y * GT_QUADRADO_MM
    ppmm = 8.0
    textura = board.generateImage((int(largura_mm * ppmm), int(altura_mm * ppmm)), 0, 1)
    u, v = np.meshgrid(np.arange(GT_RES[0], dtype=np.float32), np.arange(GT_RES[1], dtype=np.float32))
    norm = cv2.undistortPoints(np.stack([u.ravel(), v.ravel()], 1).reshape(-1, 1, 2),
                               GT_K, GT_DIST).reshape(-1, 2)
    raios = np.concatenate([norm, np.ones((len(norm), 1))], 1).astype(np.float64)
    quadros = [renderizar(textura, ppmm, R, t, raios, 1.0, rng)
               for R, t in gerar_poses(14, rng, largura_mm, altura_mm)]

    print("\n=== núcleo de captura ===")
    s = SessaoCaptura(tmp / "sessao", board, detector, min_cantos=12,
                      nitidez_min=50.0, max_por_bin=1)

    avals = [s.avaliar(q) for q in quadros]
    n_det = sum(1 for a in avals if a["cantos"] is not None)
    checar("detecta o tabuleiro nos quadros sintéticos", n_det >= 10, f"{n_det}/14")
    checar("classifica célula/escala/inclinação",
           all(a["classe"] is not None for a in avals if a["cantos"] is not None))

    exigente = SessaoCaptura(tmp / "exigente", board, detector, min_cantos=12,
                             nitidez_min=1e12, max_por_bin=1)
    a_borrado = exigente.avaliar(quadros[0])
    checar("recusa por nitidez (tabuleiro visível, mas abaixo do limiar)",
           a_borrado["cantos"] is not None and not a_borrado["capturavel"]
           and a_borrado["motivo"].startswith("BORRADO"), a_borrado["motivo"])

    vazio = np.full((GT_RES[1], GT_RES[0], 3), 200, np.uint8)
    a_vazio = s.avaliar(vazio)
    checar("recusa quadro sem tabuleiro",
           (not a_vazio["capturavel"]) and a_vazio["cantos"] is None)
    checar("registrar() recusa quadro não capturável", s.registrar(vazio, a_vazio) is None)

    salvos = [s.registrar(q, a) for q, a in zip(quadros, avals) if a["capturavel"]]
    salvos = [n for n in salvos if n]
    checar("grava as vistas aceitas", len(salvos) >= 8, f"{len(salvos)} arquivos")
    checar("grava em PNG sem perdas", all(n.endswith(".png") for n in salvos))
    checar("nomes sequenciais sem colisão", len(set(salvos)) == len(salvos))
    checar("arquivos existem em disco",
           all((s.pasta / n).exists() for n in salvos))

    r = s.resumo()
    checar("resumo conta as vistas", r["n_views"] == len(salvos), json.dumps(r["por_escala"]))
    # Contrato: `novo_bin` fecha a captura AUTOMÁTICA quando o bin lota; a
    # captura manual continua permitida — quem decide é o operador.
    checar("bin lotado deixa de ser 'novo' (fecha a captura automática)",
           all(not s.avaliar(q)["novo_bin"] for q, a in zip(quadros, avals) if a["capturavel"]),
           f"{len(s.contagem_bins)} bins ocupados, max_por_bin=1")

    antes = len(s.registros)
    removido = s.desfazer()
    checar("desfazer remove o registro e o arquivo",
           removido is not None and len(s.registros) == antes - 1
           and not (s.pasta / removido).exists(), str(removido))

    alvo = s.salvar({"interface": "teste"})
    dados = json.loads(alvo.read_text(encoding="utf-8"))
    checar("sessao.json tem imagens, cobertura e veredicto",
           {"imagens", "resumo_cobertura", "cobertura_atende", "metas_cobertura"} <= set(dados))

    s2 = SessaoCaptura(s.pasta, board, detector, 12, 50.0, 1)
    checar("retoma a sessão do disco", len(s2.registros) == len(s.registros),
           f"{len(s2.registros)} vs {len(s.registros)}")
    checar("retoma a contagem de bins", s2.contagem_bins == s.contagem_bins)

    vis = desenhar_overlay(quadros[0].copy(), avals[0], {0, 4, 8})
    checar("overlay devolve imagem do mesmo tamanho", vis.shape == quadros[0].shape)
    checar("overlay realmente desenha algo", not np.array_equal(vis, quadros[0]))

    print("\n=== app.py (análise estática) ===")
    fonte = (Path(__file__).parent / "app.py").read_text(encoding="utf-8")
    checar("GUI não reimplementa a sessão de captura",
           "SessaoCaptura" in fonte and "def avaliar" not in fonte)
    checar("GUI chama calibrar.py/validar.py como subprocesso",
           '"calibrar.py"' in fonte and '"validar.py"' in fonte)
    checar("thread de captura não toca em widgets",
           "class LoopCaptura" in fonte
           and "self.fila" in fonte.split("class App")[0])

    print("\n" + ("[APROVADO] núcleo de captura consistente."
                  if not falhas else f"[REPROVADO] {len(falhas)} falha(s): {falhas}"))
    sys.exit(0 if not falhas else 1)


if __name__ == "__main__":
    main()
