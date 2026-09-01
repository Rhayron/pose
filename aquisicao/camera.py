"""Fonte de câmera com carimbo de tempo por quadro.

Três decisões de projeto que existem por razão medível:

**A câmera captura continuamente, desde o READY.** Abrir uma webcam USB custa
centenas de milissegundos imprevisíveis: negociação DirectShow, primeiros
quadros já velhos no buffer do driver, autoexposição assentando. Se a captura
começasse no instante do clique, toda essa latência entraria no sincronismo sem
ser medida. Capturando desde antes, o clique só marca um instante em um fluxo
que já está estável.

**O carimbo é tirado entre `grab()` e `retrieve()`.** `grab()` puxa o quadro do
driver e é barato; `retrieve()` decodifica o MJPEG e custa milissegundos que
variam com o conteúdo. Carimbar depois do `read()` misturaria o tempo de
decodificação no tempo do quadro.

**O buffer interno é reduzido a 1.** Por padrão o DirectShow enfileira quadros;
com fila, `grab()` devolve um quadro antigo e o carimbo fica atrasado de um
valor que depende de quão atrás o consumidor está. Com buffer 1 o quadro é
sempre o mais recente. Nem todo driver obedece, por isso o pedido e a leitura
de volta ficam registrados.

Nada aqui converte quadro em milímetro. Isso é do `calibracao/`.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

# Modo físico do perfil calibrado. Mudar qualquer um destes invalida K.
MODO_PADRAO = {"width": 3840, "height": 2160, "fps": 30.0, "codec": "MJPG"}

# Propriedades cujo valor precisa ficar constante durante a sessão. Foco muda a
# geometria; exposição e ganho mudam brilho e ruído. Todas são amostradas
# durante a gravação, e a variação é registrada em vez de presumida ausente.
PROPS_VIGIADAS = {
    "focus": cv2.CAP_PROP_FOCUS,
    "exposure": cv2.CAP_PROP_EXPOSURE,
    "autofocus": cv2.CAP_PROP_AUTOFOCUS,
    "auto_exposure": cv2.CAP_PROP_AUTO_EXPOSURE,
    "gain": cv2.CAP_PROP_GAIN,
    "zoom": cv2.CAP_PROP_ZOOM,
}


class ErroCamera(Exception):
    """Falha dura de câmera. Nunca é degradada em aviso."""


@dataclass(frozen=True)
class Quadro:
    """Um quadro e o instante em que o driver o entregou."""

    indice: int
    imagem: np.ndarray
    monotonic_ns: int
    brilho_roi: float | None = None


@dataclass
class Estatisticas:
    n_quadros: int = 0
    intervalos_ms: list[float] = field(default_factory=list)

    def resumo(self) -> dict[str, Any]:
        if len(self.intervalos_ms) < 2:
            return {"n_quadros": self.n_quadros, "insuficiente": True}
        arr = np.asarray(self.intervalos_ms)
        mediana = float(np.median(arr))
        # Quadro perdido aparece como intervalo próximo de um múltiplo inteiro
        # do período nominal. Contar o excedente é mais honesto que comparar
        # n_quadros com fps*duração, que confunde perda com fps fora do nominal.
        perdidos = int(np.sum(np.round(arr / mediana) - 1)) if mediana > 0 else 0
        return {
            "n_quadros": self.n_quadros,
            "fps_medido": round(1000.0 / mediana, 4) if mediana > 0 else None,
            "intervalo_mediano_ms": round(mediana, 4),
            "intervalo_p95_ms": round(float(np.percentile(arr, 95)), 4),
            "intervalo_max_ms": round(float(arr.max()), 4),
            "jitter_rms_ms": round(float(np.sqrt(np.mean((arr - mediana) ** 2))), 4),
            "quadros_perdidos_estimados": max(perdidos, 0),
        }


class FonteCamera:
    """Captura contínua em thread própria, com carimbo por quadro."""

    def __init__(
        self,
        indice: int = 0,
        modo: dict[str, Any] | None = None,
        backend: int = cv2.CAP_DSHOW,
        roi_evento: tuple[int, int, int, int] | None = None,
        capacidade_buffer: int = 4,
        focus_esperado: float | None = None,
    ) -> None:
        self.indice = indice
        self.modo = dict(modo or MODO_PADRAO)
        self.backend = backend
        self.roi_evento = roi_evento
        self.focus_esperado = focus_esperado

        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._parar = threading.Event()
        self._lock = threading.Lock()

        self._ultimo: Quadro | None = None
        self._assinantes: list[Any] = []
        self._recentes: deque[Quadro] = deque(maxlen=capacidade_buffer)

        self.estatisticas = Estatisticas()
        self.props_antes: dict[str, float | None] = {}
        self.props_depois: dict[str, float | None] = {}
        self.travas: dict[str, dict[str, Any]] = {}
        self.modo_efetivo: dict[str, Any] = {}
        self.amostras_props: list[dict[str, Any]] = []
        self._t0_monotonic_ns = 0
        self._t0_wall_ns = 0

    # -- ciclo de vida ----------------------------------------------------

    def abrir(self, *, travar: bool = True) -> dict[str, Any]:
        cap = cv2.VideoCapture(self.indice, self.backend)
        if not cap.isOpened():
            raise ErroCamera(
                f"não abriu a câmera índice {self.indice}. Outra aplicação pode "
                "estar segurando o dispositivo."
            )
        self._cap = cap

        self.props_antes = self._ler_props()

        # A ordem importa: codec antes da resolução. Pedir 3840x2160 com o codec
        # ainda em YUY2 pode ser recusado por falta de banda USB e o driver cai
        # silenciosamente para uma resolução menor.
        fourcc = cv2.VideoWriter_fourcc(*str(self.modo["codec"]))
        resultados = {
            "codec": bool(cap.set(cv2.CAP_PROP_FOURCC, fourcc)),
            "width": bool(cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.modo["width"])),
            "height": bool(cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.modo["height"])),
            "fps": bool(cap.set(cv2.CAP_PROP_FPS, self.modo["fps"])),
            "buffersize": bool(cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)),
        }

        if travar:
            self.travas = self._travar_automatismos()

        self.modo_efetivo = {
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": float(cap.get(cv2.CAP_PROP_FPS)),
            "buffersize": float(cap.get(cv2.CAP_PROP_BUFFERSIZE)),
            "backend": cap.getBackendName(),
            "set_results": resultados,
        }

        efetivo = (self.modo_efetivo["width"], self.modo_efetivo["height"])
        pedido = (int(self.modo["width"]), int(self.modo["height"]))
        if efetivo != pedido:
            cap.release()
            self._cap = None
            raise ErroCamera(
                f"o driver entregou {efetivo[0]}x{efetivo[1]} em vez de "
                f"{pedido[0]}x{pedido[1]}. Os intrínsecos valem para um único "
                "modo; não há reescala implícita de K."
            )

        return self.modo_efetivo

    def iniciar(self) -> None:
        if self._cap is None:
            raise ErroCamera("chame abrir() antes de iniciar()")
        if self._thread is not None:
            return
        self._parar.clear()
        self._t0_monotonic_ns = time.perf_counter_ns()
        self._t0_wall_ns = time.time_ns()
        self._thread = threading.Thread(target=self._laco, name="captura", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._cap is not None:
            self.props_depois = self._ler_props()
            self._restaurar_automatismos()
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "FonteCamera":
        self.abrir()
        self.iniciar()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.parar()

    # -- consumo ----------------------------------------------------------

    def assinar(self, callback: Any) -> None:
        """Registra quem recebe cada quadro. Chamado na thread de captura."""
        with self._lock:
            self._assinantes.append(callback)

    def desassinar(self, callback: Any) -> None:
        with self._lock:
            if callback in self._assinantes:
                self._assinantes.remove(callback)

    def ultimo(self) -> Quadro | None:
        with self._lock:
            return self._ultimo

    def quadro_mais_proximo(self, monotonic_ns: int) -> tuple[Quadro | None, float]:
        """Quadro cujo carimbo é o mais próximo de um instante, e a distância em ms."""
        with self._lock:
            recentes = list(self._recentes)
        if not recentes:
            return None, float("nan")
        melhor = min(recentes, key=lambda q: abs(q.monotonic_ns - monotonic_ns))
        return melhor, (monotonic_ns - melhor.monotonic_ns) / 1e6

    @property
    def ancora_relogio(self) -> dict[str, Any]:
        return {
            "monotonic_ns_inicio": self._t0_monotonic_ns,
            "wall_clock_utc_inicio_ns": self._t0_wall_ns,
            "nota": (
                "monotonic serve para medir intervalos (não salta com ajuste de "
                "relógio); wall clock serve só para ancorar a sessão numa data. "
                "Não misturar os dois no mesmo cálculo."
            ),
        }

    # -- interno ----------------------------------------------------------

    def _laco(self) -> None:
        cap = self._cap
        assert cap is not None
        indice = 0
        anterior_ns: int | None = None
        proxima_amostra_ns = time.perf_counter_ns()

        while not self._parar.is_set():
            # grab() puxa do driver; retrieve() decodifica. O carimbo fica entre
            # os dois para não somar o tempo de decodificação ao tempo do quadro.
            if not cap.grab():
                time.sleep(0.001)
                continue
            carimbo = time.perf_counter_ns()
            ok, imagem = cap.retrieve()
            if not ok or imagem is None:
                continue

            brilho = None
            if self.roi_evento is not None:
                x, y, w, h = self.roi_evento
                recorte = imagem[y:y + h, x:x + w]
                if recorte.size:
                    brilho = float(recorte.mean())

            quadro = Quadro(indice=indice, imagem=imagem,
                            monotonic_ns=carimbo, brilho_roi=brilho)

            if anterior_ns is not None:
                self.estatisticas.intervalos_ms.append((carimbo - anterior_ns) / 1e6)
            anterior_ns = carimbo
            self.estatisticas.n_quadros = indice + 1

            with self._lock:
                self._ultimo = quadro
                self._recentes.append(quadro)
                assinantes = list(self._assinantes)

            for callback in assinantes:
                try:
                    callback(quadro)
                except Exception:  # noqa: BLE001 - um assinante ruim não derruba a captura
                    pass

            # Amostragem periódica das propriedades: se o driver ignorou a trava,
            # isso aparece aqui em vez de virar erro silencioso na calibração.
            if carimbo >= proxima_amostra_ns:
                proxima_amostra_ns = carimbo + 1_000_000_000
                self.amostras_props.append(
                    {"monotonic_ns": carimbo, **self._ler_props()}
                )

            indice += 1

    def _ler_props(self) -> dict[str, float | None]:
        cap = self._cap
        if cap is None:
            return {}
        leitura: dict[str, float | None] = {}
        for nome, prop in PROPS_VIGIADAS.items():
            valor = cap.get(prop)
            leitura[nome] = None if valor in (-1.0, 0.0) and nome == "zoom" else float(valor)
        return leitura

    def _travar_automatismos(self) -> dict[str, dict[str, Any]]:
        """Pede manual, lê de volta e registra se o driver obedeceu.

        Não presume obediência: em várias webcams o readback de autoexposição é
        -1 (não observável) e o `set` retorna True mesmo sem efeito.
        """
        cap = self._cap
        assert cap is not None
        pedidos = {
            "autofocus": (cv2.CAP_PROP_AUTOFOCUS, 0.0),
            "auto_exposure": (cv2.CAP_PROP_AUTO_EXPOSURE, 0.25),
        }
        resultado: dict[str, dict[str, Any]] = {}
        for nome, (prop, valor) in pedidos.items():
            retornou = bool(cap.set(prop, valor))
            time.sleep(0.05)
            lido = float(cap.get(prop))
            resultado[nome] = {
                "pedido": valor,
                "set_retornou": retornou,
                "lido": lido,
                "obedecido": abs(lido - valor) < 1e-6,
                "observavel": lido != -1.0,
            }
        return resultado

    def _restaurar_automatismos(self) -> None:
        """Devolve a câmera ao automático ao sair.

        Deixar a câmera travada em manual depois da sessão faz a próxima
        aplicação abrir quadros pretos sem explicação aparente.
        """
        cap = self._cap
        if cap is None:
            return
        try:
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 1.0)
        except cv2.error:
            pass

    def verificar_foco(self) -> dict[str, Any]:
        """Compara o foco desta sessão com o foco da calibração.

        Foco é a única propriedade da câmera que muda a geometria. Um K medido
        com foco 243 não descreve a mesma câmera com foco 280, e nada na
        imagem denuncia isso: os quadros saem nítidos, a detecção funciona, e o
        erro entra silenciosamente na escala.

        Não existe tolerância defensável aqui. As unidades de foco do
        DirectShow são arbitrárias e este projeto nunca mediu quanto K muda por
        unidade. Então qualquer diferença é relatada com a magnitude, e a
        decisão fica com quem lê. O teste que de fato responde à pergunta é
        `validar_transferencia.py` rodado NESTE foco.
        """
        observados = sorted({
            amostra["focus"] for amostra in self.amostras_props
            if amostra.get("focus") is not None
        })
        atual = self.props_antes.get("focus")

        if self.focus_esperado is None:
            return {
                "verificado": False,
                "motivo": "perfil de calibração não informou o foco de referência",
                "focus_observado": atual,
                "focus_observados_na_sessao": observados,
            }

        diferenca = None if atual is None else abs(atual - self.focus_esperado)
        estavel = len(observados) <= 1

        resultado: dict[str, Any] = {
            "verificado": True,
            "focus_da_calibracao": self.focus_esperado,
            "focus_no_inicio": atual,
            "focus_observados_na_sessao": observados,
            "estavel_durante_a_sessao": estavel,
            "diferenca": None if diferenca is None else round(diferenca, 2),
            "confere": diferenca is not None and diferenca < 1e-6,
        }

        alertas: list[str] = []
        if diferenca is not None and diferenca >= 1e-6:
            alertas.append(
                f"foco em {atual} contra {self.focus_esperado} da calibração "
                f"(diferença {diferenca:.0f} unidades). K foi medido no outro "
                "foco; qualquer número métrico desta sessão é suspeito até "
                "validar_transferencia.py rodar neste foco."
            )
        if not estavel and len(observados) > 1:
            alertas.append(
                f"o foco variou durante a sessão: {observados}. Um único K não "
                "descreve a sessão inteira. Provavelmente o autofoco continuou "
                "ativo apesar do pedido de manual."
            )
        if atual is None:
            alertas.append(
                "foco não observável neste driver: não dá para afirmar que ele "
                "bate com o da calibração, nem que ficou parado."
            )
        resultado["alertas"] = alertas
        return resultado

    def diagnostico(self) -> dict[str, Any]:
        """Tudo que a sessão precisa registrar sobre o estado da câmera."""
        variacao: dict[str, Any] = {}
        for nome in PROPS_VIGIADAS:
            valores = sorted({
                amostra[nome] for amostra in self.amostras_props
                if amostra.get(nome) is not None
            })
            variacao[nome] = {
                "valores_observados": valores,
                "constante": len(valores) <= 1,
                "n_amostras": len(self.amostras_props),
            }
        return {
            "indice": self.indice,
            "modo_pedido": self.modo,
            "modo_efetivo": self.modo_efetivo,
            "props_antes_travar": self.props_antes,
            "props_depois_da_sessao": self.props_depois,
            "travas": self.travas,
            "props_durante_a_sessao": variacao,
            "foco_contra_calibracao": self.verificar_foco(),
            "estatisticas_temporais": self.estatisticas.resumo(),
            "relogio": self.ancora_relogio,
        }
