"""
Captura ao vivo das vistas de calibração (linha de comando).

A lógica de sessão vive em `captura_core.py` e é a MESMA usada pela GUI
(`app.py`) — se as duas divergissem na decisão de aceitar um quadro, os
conjuntos de imagens deixariam de ser comparáveis.

O que a captura garante, e por quê:
  * trava foco/exposição/balanço de branco e RELÊ os valores efetivos;
  * rejeita quadros borrados (variância do Laplaciano na região do alvo);
  * guia a diversidade de poses (posição no quadro, escala, inclinação);
  * grava PNG sem perdas — JPEG desloca cantos em fração de pixel, que é
    exatamente a grandeza medida.

Teclas:  ESPAÇO capturar   A auto on/off   U desfazer   R relatório   Q/ESC sair

Uso:
    python capturar.py
    python capturar.py --camera 1 --resolucao 1280 720 --backend dshow
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2

from captura_core import (
    BACKENDS,
    SessaoCaptura,
    abrir_camera,
    desenhar_overlay,
    ler_props,
    travar_camera,
)
from nucleo import (
    METAS_COBERTURA,
    ConfigTabuleiro,
    agora,
    construir_board,
    escala_efetiva,
    novo_detector,
)


def desenhar_hud(vis, resumo, celulas, info, auto):
    m = METAS_COBERTURA
    linhas = [
        f"views {resumo['n_views']:3d}/{m['min_views']}   celulas {len(celulas)}/9   "
        f"incl {resumo['n_inclinado']}/{m['min_inclinado']}   "
        f"m.incl {resumo['n_muito_inclinado']}/{m['min_muito_inclinado']}",
        "escala " + "  ".join(f"{k}:{resumo['por_escala'].get(k, 0)}/{m['min_por_escala']}"
                              for k in ("pequeno", "medio", "grande")),
        info,
        "ESPACO capturar | A auto | U desfazer | R relatorio | Q sair",
    ]
    for i, txt in enumerate(linhas):
        y = 26 + 24 * i
        cv2.putText(vis, txt, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(vis, txt, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(vis, "AUTO" if auto else "MANUAL", (vis.shape[1] - 130, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255) if auto else (200, 200, 200), 2)
    return vis


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--backend", default="auto", choices=sorted(BACKENDS))
    ap.add_argument("--resolucao", nargs=2, type=int, default=None, metavar=("L", "A"),
                    help="USE A MESMA DOS EXPERIMENTOS. Padrão: o que a câmera entregar.")
    ap.add_argument("--tabuleiro", default="saida/tabuleiro.json")
    ap.add_argument("--saida", default=None, help="padrão: capturas/<AAAAMMDD_HHMMSS>")
    ap.add_argument("--min-cantos", type=int, default=12)
    ap.add_argument("--nitidez-min", type=float, default=120.0)
    ap.add_argument("--max-por-bin", type=int, default=3)
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--cooldown", type=float, default=0.8)
    ap.add_argument("--auto-exposure", type=float, default=0.25)
    ap.add_argument("--exposicao", type=float, default=None)
    ap.add_argument("--foco", type=float, default=None)
    args = ap.parse_args()

    cfg = ConfigTabuleiro.carregar(Path(args.tabuleiro))
    # Na captura só a geometria relativa importa; a escala medida é exigida
    # na calibração. Por isso aqui o nominal é aceitável.
    quadrado, marcador, fonte_escala = escala_efetiva(cfg, permitir_nominal=True)
    board, _ = construir_board(cfg, quadrado, marcador)
    detector = novo_detector(board)

    cap = abrir_camera(args.camera, args.backend, args.resolucao)
    props_antes = ler_props(cap)
    trava = travar_camera(cap, args.auto_exposure, args.exposicao, args.foco)
    for _ in range(10):  # descarta quadros do período de acomodação
        cap.read()
    props_depois = ler_props(cap)

    print("\n--- estado da câmera (pedido -> lido) ---")
    for nome, d in trava.items():
        print(f"  {'ok ' if d['obedecido'] else '!! '}{nome:15s} "
              f"pedido={d['pedido']:<10g} lido={d['lido']:<10g} set={d['set_retornou']}")
    print("  (linhas com !! = o driver ignorou o pedido. Trave pelo app da câmera\n"
          "   do Windows ou pelo utilitário do fabricante e confira aqui de novo.)\n")

    pasta = Path(args.saida or f"capturas/{time.strftime('%Y%m%d_%H%M%S')}")
    sessao = SessaoCaptura(pasta, board, detector, args.min_cantos,
                           args.nitidez_min, args.max_por_bin)
    if sessao.registros:
        print(f"[ok] retomando sessão com {len(sessao.registros)} vistas já capturadas")
    auto, ultimo = args.auto, 0.0
    print(f"[ok] gravando em {pasta.resolve()}   (auto={'ON' if auto else 'OFF'})")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("[aviso] falha ao ler quadro")
            continue
        aval = sessao.avaliar(frame)
        resumo = sessao.resumo()
        celulas = {r["celula"] for r in sessao.registros}
        info = aval["motivo"]
        if aval["cantos"] is not None:
            info = (f"cantos {aval['n_cantos']} | nitidez {aval['nitidez']:.0f} | "
                    f"tilt {aval['tilt']:.0f} deg | {aval['classe']['escala']}/"
                    f"{aval['classe']['tilt']} | bin {aval['no_bin']}/{args.max_por_bin} "
                    f"| {aval['motivo']}")

        vis = desenhar_overlay(frame.copy(), aval, celulas)
        cv2.imshow("calibracao - captura", desenhar_hud(vis, resumo, celulas, info, auto))
        tecla = cv2.waitKey(1) & 0xFF

        deve = (tecla == 32) or (auto and aval["capturavel"] and aval["novo_bin"]
                                 and (time.time() - ultimo) > args.cooldown)
        if deve:
            nome = sessao.registrar(frame, aval)
            if nome:
                ultimo = time.time()
                print(f"  + {nome}  cantos={aval['n_cantos']}  nitidez={aval['nitidez']:.0f}  "
                      f"tilt={aval['tilt']:.0f}deg  bin={aval['chave']}")
            else:
                print(f"  . recusada: {aval['motivo']}")

        if tecla in (ord("a"), ord("A")):
            auto = not auto
        elif tecla in (ord("u"), ord("U")):
            removido = sessao.desfazer()
            print(f"  - desfeita {removido}" if removido else "  . nada a desfazer")
        elif tecla in (ord("r"), ord("R")):
            print(json.dumps(sessao.resumo(), indent=2, ensure_ascii=False))
        elif tecla in (ord("q"), ord("Q"), 27):
            break

    cap.release()
    cv2.destroyAllWindows()

    alvo = sessao.salvar({
        "camera": {"indice": args.camera, "backend": args.backend},
        "props_antes_travar": props_antes,
        "props_depois_travar": props_depois,
        "trava": trava,
        "resolucao_efetiva": [int(props_depois["FRAME_WIDTH"]), int(props_depois["FRAME_HEIGHT"])],
        "tabuleiro": args.tabuleiro,
        "fonte_escala_na_captura": fonte_escala,
        "interface": "cli",
        "iniciado_por": "capturar.py",
        "gerado_em": agora(),
    })
    atende, faltas = sessao.veredicto_cobertura()
    print("\n--- cobertura ---")
    print(json.dumps(sessao.resumo(), indent=2, ensure_ascii=False))
    print(f"[ok] {alvo}")
    if atende:
        print(f"\n[ok] cobertura atende as metas pré-registradas.\n"
              f"     python calibrar.py --imagens {pasta}")
    else:
        print("\n[ATENÇÃO] cobertura INSUFICIENTE — faltam: " + "; ".join(faltas))
        print("     Calibrar assim mede a lente só onde o tabuleiro esteve;")
        print("     a distorção nas bordas vira extrapolação. Continue nesta sessão:")
        print(f"     python capturar.py --saida {pasta}")


if __name__ == "__main__":
    main()
