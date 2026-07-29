"""
Núcleo de captura — usado tanto pela CLI (`capturar.py`) quanto pela GUI (`app.py`).

Fonte única da lógica de sessão: se a GUI e a CLI divergirem na decisão de
aceitar um quadro, os dois conjuntos de imagens deixam de ser comparáveis.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

from nucleo import (
    METAS_COBERTURA,
    agora,
    ambiente,
    classificar,
    cobertura_atende,
    detectar,
    fracao_area,
    inclinacao_graus,
    nitidez_roi,
    resumo_cobertura,
)

BACKENDS = {
    "auto": cv2.CAP_ANY,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "v4l2": cv2.CAP_V4L2,
}

PROPS_RELEVANTES = [
    ("FRAME_WIDTH", cv2.CAP_PROP_FRAME_WIDTH),
    ("FRAME_HEIGHT", cv2.CAP_PROP_FRAME_HEIGHT),
    ("FPS", cv2.CAP_PROP_FPS),
    ("AUTOFOCUS", cv2.CAP_PROP_AUTOFOCUS),
    ("FOCUS", cv2.CAP_PROP_FOCUS),
    ("AUTO_EXPOSURE", cv2.CAP_PROP_AUTO_EXPOSURE),
    ("EXPOSURE", cv2.CAP_PROP_EXPOSURE),
    ("AUTO_WB", cv2.CAP_PROP_AUTO_WB),
    ("WB_TEMPERATURE", cv2.CAP_PROP_WB_TEMPERATURE),
    ("BRIGHTNESS", cv2.CAP_PROP_BRIGHTNESS),
    ("CONTRAST", cv2.CAP_PROP_CONTRAST),
    ("GAIN", cv2.CAP_PROP_GAIN),
    ("ZOOM", cv2.CAP_PROP_ZOOM),
]

RESOLUCOES_COMUNS = ["640x480", "1280x720", "1920x1080", "2560x1440", "3840x2160"]


def ler_props(cap) -> dict:
    return {nome: float(cap.get(pid)) for nome, pid in PROPS_RELEVANTES}


def abrir_camera(indice: int, backend: str = "auto", resolucao=None):
    cap = cv2.VideoCapture(int(indice), BACKENDS[backend])
    if not cap.isOpened():
        raise RuntimeError(
            f"não abriu a câmera {indice} (backend {backend}). "
            f"Tente outro índice ou outro backend (dshow/msmf)."
        )
    if resolucao:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(resolucao[0]))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(resolucao[1]))
    # Buffer de 1: em resoluções altas a detecção é mais lenta que a câmera, e um
    # buffer maior entregaria quadros velhos — você capturaria uma pose que o
    # tabuleiro já não está fazendo.
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def procurar_cameras(max_indice: int = 5, backend: str = "auto") -> list[int]:
    achadas = []
    for i in range(max_indice + 1):
        try:
            cap = cv2.VideoCapture(i, BACKENDS[backend])
            if cap.isOpened() and cap.read()[0]:
                achadas.append(i)
            cap.release()
        except cv2.error:
            pass
    return achadas


def travar_camera(cap, auto_exposure=0.25, exposicao=None, foco=None) -> dict:
    """Tenta desligar os automatismos e RELÊ o que ficou.

    Autofoco muda a distância focal entre quadros: calibrar com ele ligado
    estima um `f` que não existiu em instante nenhum. O readback é a prova.
    """
    pedidos = [
        ("AUTOFOCUS", cv2.CAP_PROP_AUTOFOCUS, 0.0),
        ("AUTO_WB", cv2.CAP_PROP_AUTO_WB, 0.0),
        ("AUTO_EXPOSURE", cv2.CAP_PROP_AUTO_EXPOSURE, float(auto_exposure)),
    ]
    if foco is not None:
        pedidos.append(("FOCUS", cv2.CAP_PROP_FOCUS, float(foco)))
    if exposicao is not None:
        pedidos.append(("EXPOSURE", cv2.CAP_PROP_EXPOSURE, float(exposicao)))

    resultado = {}
    for nome, pid, valor in pedidos:
        aceito = bool(cap.set(pid, valor))
        time.sleep(0.15)
        lido = float(cap.get(pid))
        resultado[nome] = {
            "pedido": valor,
            "set_retornou": aceito,
            "lido": lido,
            "obedecido": abs(lido - valor) < 1e-6,
        }
    return resultado


class SessaoCaptura:
    """Contabilidade de uma sessão de captura (retomável)."""

    def __init__(self, pasta, board, detector, min_cantos=12, nitidez_min=120.0,
                 max_por_bin=3, max_lado_deteccao=1600):
        self.pasta = Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.board = board
        self.detector = detector
        self.min_cantos = int(min_cantos)
        self.nitidez_min = float(nitidez_min)
        self.max_por_bin = int(max_por_bin)
        # A detecção AO VIVO roda em uma versão reduzida do quadro: em 4K o
        # limiar adaptativo varre 8 MP várias vezes e a orientação da captura
        # fica inutilizável (segundos por quadro). O que é gravado continua
        # sendo o quadro CHEIO, e `calibrar.py` redetecta nele em resolução
        # plena — a precisão de canto que entra na medida não é afetada.
        self.max_lado_deteccao = int(max_lado_deteccao) if max_lado_deteccao else 0
        self.registros: list[dict] = []
        self.contagem_bins: dict = {}
        # Contador monotônico: um número JAMAIS é reaproveitado, nem depois de
        # desfazer. Se `img_0007.png` aparece num log, refere-se a uma única
        # imagem — reaproveitar o número tornaria o registro ambíguo.
        self._contador = 0
        # Mudar o critério de aceite no meio da sessão é legítimo (calibrar o
        # limiar faz parte do trabalho), mas TEM de ficar registrado: sem isso
        # o conjunto final teria vistas admitidas sob réguas diferentes sem
        # que o arquivo dissesse nada.
        self.historico_criterios: list[dict] = []
        self._carregar()

    # -- estado ------------------------------------------------------------
    def _carregar(self):
        alvo = self.pasta / "sessao.json"
        if not alvo.exists():
            return
        dados = json.loads(alvo.read_text(encoding="utf-8")).get("imagens", [])
        self.registros = [r for r in dados if (self.pasta / r["arquivo"]).exists()]
        for r in self.registros:
            k = (r["celula"], r["escala"], r["tilt"])
            self.contagem_bins[k] = self.contagem_bins.get(k, 0) + 1
        # retoma acima do maior número já usado, inclusive de vistas desfeitas
        usados = [int(p.stem.split("_")[-1]) for p in self.pasta.glob("img_*.png")
                  if p.stem.split("_")[-1].isdigit()]
        usados += [int(r["arquivo"].split("_")[-1].split(".")[0]) for r in dados
                   if r["arquivo"].split("_")[-1].split(".")[0].isdigit()]
        self._contador = max(usados, default=0)

    def ajustar(self, min_cantos=None, nitidez_min=None, max_por_bin=None) -> list[str]:
        """Altera os critérios de aceite em tempo de sessão, deixando rastro."""
        mudancas = []
        for nome, novo, conv in (("min_cantos", min_cantos, int),
                                 ("nitidez_min", nitidez_min, float),
                                 ("max_por_bin", max_por_bin, int)):
            if novo is None:
                continue
            try:
                novo = conv(novo)
            except (TypeError, ValueError):
                continue
            antigo = getattr(self, nome)
            if novo != antigo:
                setattr(self, nome, novo)
                mudancas.append(f"{nome}: {antigo:g} -> {novo:g}")
                self.historico_criterios.append(
                    {"quando": agora(), "apos_n_vistas": len(self.registros),
                     "criterio": nome, "de": antigo, "para": novo})
        return mudancas

    def resumo(self) -> dict:
        return resumo_cobertura(self.registros)

    def veredicto_cobertura(self):
        return cobertura_atende(self.resumo())

    # -- avaliação de um quadro -------------------------------------------
    def avaliar(self, frame, lado_max=None) -> dict:
        """Avalia um quadro.

        `lado_max=0` detecta no quadro CHEIO — mais caro, porém é a mesma
        detecção que `calibrar.py` fará depois, então aceitar/recusar aqui
        coincide com o que vale. Use no clique.
        `lado_max=N` detecta numa versão reduzida a N px de lado — é o guia
        contínuo. `None` usa o padrão da sessão.

        Medido em quadro real 4K: 640 px = 5,8 ms; cheio = 71,5 ms.

        Em qualquer caso nitidez, inclinação e classificação são medidas no
        quadro CHEIO (os cantos voltam à escala original antes disso), então
        os números do guia são comparáveis aos do clique.
        """
        if lado_max is None:
            lado_max = self.max_lado_deteccao
        quadro_det, fator = frame, 1.0
        lado = max(frame.shape[:2])
        if lado_max and lado > lado_max:
            fator = lado_max / lado
            quadro_det = cv2.resize(frame, None, fx=fator, fy=fator,
                                    interpolation=cv2.INTER_AREA)
        cantos, ids = detectar(self.detector, quadro_det)
        if cantos is not None and fator != 1.0:
            # devolve os cantos ao referencial do quadro cheio, para que
            # nitidez, inclinação e classificação sejam medidas nele
            cantos = (cantos / fator).astype(np.float32)
        if cantos is None:
            return {"cantos": None, "ids": None, "n_cantos": 0, "nitidez": 0.0,
                    "tilt": 0.0, "classe": None, "chave": None,
                    "capturavel": False, "novo_bin": False, "motivo": "sem tabuleiro"}
        nit = nitidez_roi(frame, cantos)
        tilt = inclinacao_graus(self.board, cantos, ids, frame.shape)
        classe = classificar(cantos, frame.shape, tilt)
        chave = (classe["celula"], classe["escala"], classe["tilt"])
        n = int(len(ids))
        if n < self.min_cantos:
            motivo, ok = f"cantos {n} < {self.min_cantos} (aproxime ou melhore a luz)", False
        elif nit < self.nitidez_min:
            motivo, ok = f"BORRADO — nitidez {nit:.0f} < {self.nitidez_min:.0f}", False
        else:
            motivo, ok = "pronto para capturar", True
        return {"cantos": cantos, "ids": ids, "n_cantos": n, "nitidez": nit,
                "tilt": tilt, "classe": classe, "chave": chave,
                "area": fracao_area(cantos, frame.shape),
                "capturavel": ok, "motivo": motivo,
                "novo_bin": self.contagem_bins.get(chave, 0) < self.max_por_bin,
                "no_bin": self.contagem_bins.get(chave, 0)}

    # -- ações -------------------------------------------------------------
    def registrar(self, frame, aval) -> str | None:
        if not aval["capturavel"]:
            return None
        self.pasta.mkdir(parents=True, exist_ok=True)  # a pasta pode ter sumido
        self._contador += 1
        while (self.pasta / f"img_{self._contador:04d}.png").exists():
            self._contador += 1
        nome = f"img_{self._contador:04d}.png"
        cv2.imwrite(str(self.pasta / nome), frame)  # PNG: sem perdas
        self.registros.append({
            "arquivo": nome, "n_cantos": aval["n_cantos"],
            "nitidez": round(aval["nitidez"], 1), "tilt_graus": round(aval["tilt"], 1),
            **aval["classe"],
        })
        k = aval["chave"]
        self.contagem_bins[k] = self.contagem_bins.get(k, 0) + 1
        return nome

    def desfazer(self) -> str | None:
        if not self.registros:
            return None
        r = self.registros.pop()
        (self.pasta / r["arquivo"]).unlink(missing_ok=True)
        k = (r["celula"], r["escala"], r["tilt"])
        restante = self.contagem_bins.get(k, 1) - 1
        # remover a chave zerada mantém o dicionário idêntico ao que seria
        # reconstruído a partir do disco — estados divergentes aqui fariam a
        # sessão retomada se comportar diferente da original.
        if restante > 0:
            self.contagem_bins[k] = restante
        else:
            self.contagem_bins.pop(k, None)
        return r["arquivo"]

    def salvar(self, extras: dict | None = None) -> Path:
        resumo = self.resumo()
        atende, faltas = cobertura_atende(resumo)
        dados = {
            "criterios_captura": {"min_cantos": self.min_cantos,
                                  "nitidez_min": self.nitidez_min,
                                  "max_por_bin": self.max_por_bin,
                                  "max_lado_deteccao_ao_vivo": self.max_lado_deteccao,
                                  "nota_deteccao": "a detecção ao vivo é reduzida (só orienta "
                                                   "a captura); calibrar.py redetecta no PNG "
                                                   "em resolução plena"},
            "historico_criterios": self.historico_criterios,
            "metas_cobertura": METAS_COBERTURA,
            "resumo_cobertura": resumo,
            "cobertura_atende": atende,
            "cobertura_faltando": faltas,
            "imagens": self.registros,
            "ambiente": ambiente(),
            "encerrado_em": agora(),
        }
        dados.update(extras or {})
        self.pasta.mkdir(parents=True, exist_ok=True)
        alvo = self.pasta / "sessao.json"
        alvo.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
        return alvo


# -- desenho ---------------------------------------------------------------

def desenhar_overlay(vis, aval, celulas_cobertas, escala=1.0):
    """Grade 3x3 (células já cobertas em verde) + cantos detectados.

    `escala` converte cantos medidos no quadro cheio para o preview reduzido.
    `aval` pode ser vazio: sem detecção, desenha só a grade.
    """
    h, w = vis.shape[:2]
    for i in (1, 2):
        cv2.line(vis, (w * i // 3, 0), (w * i // 3, h), (70, 70, 70), 1)
        cv2.line(vis, (0, h * i // 3), (w, h * i // 3), (70, 70, 70), 1)
    for c in celulas_cobertas:
        x0, y0 = (c % 3) * w // 3, (c // 3) * h // 3
        cv2.rectangle(vis, (x0 + 3, y0 + 3), (x0 + w // 3 - 3, y0 + h // 3 - 3),
                      (0, 150, 0), 2)
    if aval and aval.get("cantos") is not None:
        cor = (0, 255, 0) if aval.get("capturavel") else (0, 165, 255)
        # Desenho próprio em vez de cv2.aruco.drawDetectedCornersCharuco: aquela
        # função exige que cantos e ids tenham exatamente o mesmo `total()` e
        # dispara uma exceção — dentro da thread de captura, matando-a em
        # silêncio. Aqui um canto a mais ou a menos não derruba nada.
        pts = np.asarray(aval["cantos"], np.float32).reshape(-1, 2) * escala
        ids = np.asarray(aval.get("ids", [])).reshape(-1)
        for i, (x, y) in enumerate(pts):
            p = (int(round(x)), int(round(y)))
            cv2.drawMarker(vis, p, cor, cv2.MARKER_CROSS, 12, 1, cv2.LINE_AA)
            cv2.circle(vis, p, 5, cor, 1, cv2.LINE_AA)
            if i < len(ids):
                cv2.putText(vis, str(int(ids[i])), (p[0] + 7, p[1] - 7),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, cor, 1, cv2.LINE_AA)
        if len(pts) >= 4:
            casco = cv2.convexHull(pts.astype(np.float32)).astype(np.int32)
            cv2.polylines(vis, [casco], True, cor, 1, cv2.LINE_AA)
    return vis


def desenhar_estado(vis, aval, faltando=(), completo=False, por_linha=4, passo=None):
    """Faixa do estado. Com `passo`, mostra o roteiro em vez da cobertura."""
    if passo is not None:
        titulo, faltas, estaveis, precisa = passo
        cor = (40, 140, 40) if not faltas else (40, 110, 200)
        linhas = [titulo]
        if faltas:
            linhas += [f"  -> {f}" for f in faltas[:3]]
        else:
            barra = "#" * estaveis + "." * max(0, precisa - estaveis)
            linhas.append(f"  SEGURE ASSIM  [{barra}]  gravando...")
        if aval and aval.get("cantos") is not None:
            linhas.append(f"  area {aval.get('area', 0)*100:.1f}%   "
                          f"tilt {aval['tilt']:.0f} graus   "
                          f"cantos {aval['n_cantos']}   nitidez {aval['nitidez']:.0f}")
        h = 26 * len(linhas) + 10
        faixa = vis[:h].copy()
        cv2.rectangle(vis, (0, 0), (vis.shape[1], h), cor, -1)
        cv2.addWeighted(faixa, 0.3, vis[:h], 0.7, 0, vis[:h])
        for i, txt in enumerate(linhas):
            cv2.putText(vis, txt, (10, 24 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX,
                        0.62 if i == 0 else 0.5, (255, 255, 255),
                        2 if i == 0 else 1, cv2.LINE_AA)
        return vis
    return _estado_cobertura(vis, aval, faltando, completo, por_linha)


def _estado_cobertura(vis, aval, faltando=(), completo=False, por_linha=4):
    """Faixa com a pose atual e o placar do que ainda falta para fechar.

    `faltando` são itens já formatados com contagem ("medio 1/4"), para que o
    progresso seja visível a cada captura sem precisar olhar o painel lateral.
    """
    if not aval or aval.get("cantos") is None:
        linhas, cor = ["sem tabuleiro"], (60, 60, 200)
    else:
        c = aval["classe"]
        cor = (60, 160, 60) if aval.get("capturavel") else (40, 130, 210)
        linhas = [f"{c['escala'].upper()}  /  {c['tilt'].upper()}  {aval['tilt']:.0f} graus",
                  f"cantos {aval['n_cantos']}   nitidez {aval['nitidez']:.0f}"]
    if completo:
        linhas.append("COBERTURA COMPLETA - pode parar e calibrar")
        cor = (40, 140, 40)
    elif faltando:
        itens = list(faltando)
        for i in range(0, len(itens), por_linha):
            bloco = "   ".join(itens[i:i + por_linha])
            linhas.append(("falta: " if i == 0 else "       ") + bloco)

    h = 26 * len(linhas) + 10
    faixa = vis[:h].copy()
    cv2.rectangle(vis, (0, 0), (vis.shape[1], h), cor, -1)
    cv2.addWeighted(faixa, 0.35, vis[:h], 0.65, 0, vis[:h])
    for i, txt in enumerate(linhas):
        cv2.putText(vis, txt, (10, 24 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX,
                    0.62 if i == 0 else 0.5, (255, 255, 255), 2 if i == 0 else 1, cv2.LINE_AA)
    return vis
