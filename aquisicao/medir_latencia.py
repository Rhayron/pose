"""Mede a latência do pipeline da câmera — de sensor a quadro entregue.

O problema
----------
O carimbo de tempo de um quadro é tirado quando o driver o entrega. Entre a
exposição do sensor e essa entrega há transferência USB, decodificação MJPEG e
buffering, que somam dezenas de milissegundos. Esse atraso é sistemático: todo
quadro está "atrasado" pelo mesmo valor.

Se o único evento de referência fosse o próprio vídeo, o atraso cancelaria e
não importaria. Mas o marcador de clique vem do relógio do sistema operacional,
sem esse atraso. Comparar os dois sem compensar introduz um viés constante de
uma latência inteira — direto na associação pose↔ultrassom.

O método
--------
A tela do computador vira o gerador de evento. O script pisca a tela de preto
para branco em um instante conhecido `t_pisca` (relógio monotônico), com a
câmera apontada para a tela, e observa em que quadro a mudança aparece.

    latência_medida = t_quadro_detectado − t_pisca

`latência_medida` inclui o tempo de resposta do monitor (tipicamente 1–5 ms em
LCD) somado à latência da câmera. É um limite superior da latência da câmera,
e é o número certo para corrigir um evento gerado na tela.

O piscar é repetido N vezes com intervalos aleatórios. Intervalo fixo poderia
entrar em batimento com o período de quadro e enviesar sempre para o mesmo
lado; aleatório distribui a fase uniformemente. Relata-se a distribuição
inteira, não só a média — se o P90 estiver muito acima da mediana, a latência
não é constante e compensar por um número só seria enganoso.

Uso
---
    python medir_latencia.py --camera 0 --repeticoes 20

Aponte a câmera para a tela, com a janela do script visível e ocupando boa
parte do campo de visão. Ambiente sem luz forte batendo na tela.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from camera import ErroCamera, FonteCamera  # noqa: E402

DEGRAU_MIN = 25.0


class Medicao:
    def __init__(self, fonte: FonteCamera, repeticoes: int) -> None:
        self.fonte = fonte
        self.repeticoes = repeticoes
        self.eventos: list[dict[str, Any]] = []
        self._quadros: list[tuple[int, float]] = []
        self._coletando = False

    def _receber(self, quadro: Any) -> None:
        if self._coletando and quadro.brilho_roi is not None:
            self._quadros.append((quadro.monotonic_ns, quadro.brilho_roi))

    def executar(self, root: tk.Tk, tela: tk.Canvas) -> None:
        self.fonte.assinar(self._receber)

        for n in range(self.repeticoes):
            # Preto, esperar assentar, e só então piscar.
            tela.configure(background="black")
            root.update()
            time.sleep(0.35 + random.random() * 0.25)

            self._quadros.clear()
            self._coletando = True
            time.sleep(0.12)  # linha de base antes do degrau

            tela.configure(background="white")
            root.update_idletasks()
            root.update()
            t_pisca = time.perf_counter_ns()

            time.sleep(0.35)
            self._coletando = False

            evento = self._localizar_degrau(t_pisca)
            evento["repeticao"] = n
            self.eventos.append(evento)
            print(
                f"  {n + 1:2d}/{self.repeticoes}  "
                + (f"{evento['latencia_ms']:.2f} ms" if evento["detectado"]
                   else f"não detectado ({evento.get('motivo')})")
            )

        self.fonte.desassinar(self._receber)

    def _localizar_degrau(self, t_pisca: int) -> dict[str, Any]:
        if len(self._quadros) < 4:
            return {"detectado": False, "motivo": "quadros insuficientes"}

        carimbos = np.array([q[0] for q in self._quadros], dtype=np.int64)
        brilhos = np.array([q[1] for q in self._quadros], dtype=float)

        anteriores = brilhos[carimbos < t_pisca]
        if len(anteriores) < 2:
            return {"detectado": False, "motivo": "sem linha de base antes do pisca"}

        base = float(np.median(anteriores))
        posteriores = np.where((carimbos >= t_pisca) & (brilhos > base + DEGRAU_MIN))[0]
        if len(posteriores) == 0:
            return {
                "detectado": False,
                "motivo": f"nenhum quadro passou de {base:.1f}+{DEGRAU_MIN}",
                "brilho_base": round(base, 2),
                "brilho_max": round(float(brilhos.max()), 2),
            }

        i = int(posteriores[0])
        latencia_ms = (carimbos[i] - t_pisca) / 1e6
        return {
            "detectado": True,
            "latencia_ms": round(float(latencia_ms), 3),
            "brilho_base": round(base, 2),
            "brilho_detectado": round(float(brilhos[i]), 2),
            "quadros_na_janela": len(self._quadros),
        }


def resumir(eventos: list[dict[str, Any]], periodo_ms: float | None) -> dict[str, Any]:
    validos = [e["latencia_ms"] for e in eventos if e.get("detectado")]
    if not validos:
        return {"ok": False, "motivo": "nenhuma repetição detectada"}

    arr = np.asarray(validos)
    mediana = float(np.median(arr))
    p90 = float(np.percentile(arr, 90))
    dispersao = float(arr.max() - arr.min())

    interpretacao: list[str] = []
    # A quantização por período de quadro já explica uma dispersão de até um
    # período: o degrau pode cair em qualquer fase da janela de exposição.
    if periodo_ms and dispersao <= periodo_ms * 1.5:
        interpretacao.append(
            f"dispersão de {dispersao:.1f} ms é compatível com a quantização de "
            f"um período de quadro ({periodo_ms:.1f} ms). A latência se comporta "
            "como constante; compensar pela mediana é defensável."
        )
    else:
        interpretacao.append(
            f"dispersão de {dispersao:.1f} ms excede um período de quadro "
            f"({periodo_ms:.1f} ms) se houver. A latência NÃO é constante — "
            "compensar por um único número introduziria erro variável. "
            "Investigue carga de CPU, USB compartilhado ou buffer do driver."
        )
    interpretacao.append(
        "O valor inclui o tempo de resposta do monitor (1–5 ms em LCD típico), "
        "então é limite superior da latência só da câmera."
    )

    return {
        "ok": True,
        "n_validas": len(validos),
        "n_tentativas": len(eventos),
        "latencia_mediana_ms": round(mediana, 3),
        "latencia_p90_ms": round(p90, 3),
        "latencia_min_ms": round(float(arr.min()), 3),
        "latencia_max_ms": round(float(arr.max()), 3),
        "dispersao_ms": round(dispersao, 3),
        "periodo_de_quadro_ms": round(periodo_ms, 3) if periodo_ms else None,
        "interpretacao": interpretacao,
        "usar_em_gravar_py": f"--latencia-ms {mediana:.1f}",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--repeticoes", type=int, default=20)
    ap.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "W", "H"),
                    default=[760, 390, 400, 300],
                    help="região do quadro que enxerga a tela")
    ap.add_argument("--output", default=str(RAIZ / "latencia.json"))
    args = ap.parse_args(argv)

    fonte = FonteCamera(indice=args.camera, roi_evento=tuple(args.roi))
    try:
        fonte.abrir()
    except ErroCamera as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    fonte.iniciar()

    print("Aponte a câmera para a tela. A janela vai piscar; não a cubra.")
    time.sleep(2.0)  # deixar a autoexposição assentar antes de medir

    root = tk.Tk()
    root.title("medindo latência — não cubra esta janela")
    root.attributes("-fullscreen", True)
    tela = tk.Canvas(root, background="black", highlightthickness=0)
    tela.pack(fill="both", expand=True)
    root.update()

    medicao = Medicao(fonte, args.repeticoes)
    try:
        medicao.executar(root, tela)
    finally:
        root.destroy()
        temporal = fonte.estatisticas.resumo()
        fonte.parar()

    resumo = resumir(medicao.eventos, temporal.get("intervalo_mediano_ms"))
    documento = {
        "schema": {"name": "pose.latencia_pipeline_camera", "version": 1},
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metodo": (
            "degrau de luminância gerado na tela em instante conhecido, "
            "detectado nos quadros que chegam; intervalos aleatórios entre "
            "repetições para distribuir a fase"
        ),
        "camera": fonte.diagnostico(),
        "resumo": resumo,
        "repeticoes": medicao.eventos,
    }
    saida = Path(args.output)
    saida.write_text(
        json.dumps(documento, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    print()
    print(json.dumps(resumo, indent=2, ensure_ascii=False))
    print(f"\nrelatório em {saida}")
    return 0 if resumo.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
