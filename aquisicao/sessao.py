"""Sessão de gravação: vídeo, carimbos por quadro e metadados de sincronismo.

O que esta camada garante, e o que ela explicitamente não garante:

**Garante.** Que cada quadro gravado tem um carimbo monotônico tirado no
instante em que o driver o entregou; que o instante do marcador (clique) está
no mesmo relógio dos quadros; que o vídeo escrito tem o mesmo número de quadros
que a tabela de carimbos; que a proveniência da calibração usada está selada
junto.

**Não garante.** Que o marcador coincide com o primeiro disparo do ultrassom.
O clique é um evento de interface: entre ele e o primeiro tiro do pulser há
latência do software proprietário, desconhecida e provavelmente variável. E
entre a exposição do sensor e a entrega do quadro pelo USB há a latência de
pipeline da câmera, que `medir_latencia.py` mede mas que precisa ser medida em
cada montagem.

Por isso o JSON traz `sincronismo.qualidade`, que degrada explicitamente quando
só existe o marcador de clique. Um alinhamento grosseiro declarado como
grosseiro é utilizável; um alinhamento grosseiro declarado como fino contamina
tudo que vier depois.
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from camera import FonteCamera, Quadro

SCHEMA = {"name": "pose.sessao_aquisicao", "version": 1}

# Um degrau de brilho na ROI acima disto conta como evento luminoso. O valor é
# alto de propósito: variação de iluminação ambiente e ruído de sensor ficam
# muito abaixo de 25 níveis de cinza de degrau entre quadros consecutivos.
DEGRAU_EVENTO_MIN = 25.0


class ErroSessao(Exception):
    pass


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Gravacao:
    """Escreve quadros em disco sem bloquear a thread de captura.

    A escrita vai para uma fila consumida por outra thread. Se o disco engasgar,
    a captura continua e a fila cresce — perder quadro por I/O seria perder
    justamente o instante que a sessão existe para registrar.
    """

    def __init__(
        self,
        destino: Path,
        modo: dict[str, Any],
        *,
        codec: str = "MJPG",
        limite_fila: int = 600,
    ) -> None:
        self.destino = Path(destino)
        self.destino.parent.mkdir(parents=True, exist_ok=True)
        self.modo = modo
        self.codec = codec

        self._fila: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=limite_fila)
        self._writer: cv2.VideoWriter | None = None
        self._thread: threading.Thread | None = None
        self.quadros: list[dict[str, Any]] = []
        self.descartados_por_fila = 0
        self._n_escritos = 0

    def iniciar(self) -> None:
        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        writer = cv2.VideoWriter(
            str(self.destino), fourcc, float(self.modo["fps"]),
            (int(self.modo["width"]), int(self.modo["height"])),
        )
        if not writer.isOpened():
            raise ErroSessao(
                f"não abriu o escritor de vídeo em {self.destino} com codec "
                f"{self.codec}. Verifique se o OpenCV tem suporte a esse codec."
            )
        self._writer = writer
        self._thread = threading.Thread(target=self._laco, name="escrita", daemon=True)
        self._thread.start()

    def receber(self, quadro: Quadro) -> None:
        """Chamado pela thread de captura para cada quadro."""
        registro = {
            "i": len(self.quadros),
            "indice_fonte": quadro.indice,
            "monotonic_ns": quadro.monotonic_ns,
        }
        if quadro.brilho_roi is not None:
            registro["brilho_roi"] = round(quadro.brilho_roi, 3)
        self.quadros.append(registro)
        try:
            self._fila.put_nowait(quadro.imagem)
        except queue.Full:
            # Registrado, nunca silencioso: um quadro na tabela sem quadro no
            # vídeo quebraria a correspondência índice↔carimbo.
            self.descartados_por_fila += 1
            self.quadros.pop()

    def encerrar(self) -> None:
        if self._thread is not None:
            self._fila.put(None)
            self._thread.join(timeout=30.0)
            self._thread = None
        if self._writer is not None:
            self._writer.release()
            self._writer = None

    def _laco(self) -> None:
        while True:
            imagem = self._fila.get()
            if imagem is None:
                return
            if self._writer is not None:
                self._writer.write(imagem)
                self._n_escritos += 1

    @property
    def n_escritos(self) -> int:
        return self._n_escritos


def detectar_evento_luminoso(
    quadros: list[dict[str, Any]],
    degrau_min: float = DEGRAU_EVENTO_MIN,
    exposicao_ns: int | None = None,
) -> dict[str, Any]:
    """Acha a transição de brilho na ROI e interpola o instante dentro do quadro.

    **Por que não pelo maior salto.** A tentação é pegar `argmax(|diff|)`. Isso
    erra quando existe um quadro de transição parcial: a sequência vira
    `baixo → intermediário → alto`, com dois saltos, e o maior deles é o
    *segundo* sempre que a luz acendeu na segunda metade da exposição. O
    algoritmo apontaria o quadro seguinte ao correto e perderia a interpolação.

    **O que é feito.** Os dois patamares vêm dos percentis 10 e 90 do sinal
    inteiro, que são imunes ao quadro de transição por ser um só. O primeiro
    quadro que atinge 95% da amplitude marca o fim da transição; o quadro
    imediatamente anterior é o candidato a intermediário.

    **A interpolação.** A janela de exposição do quadro `k` termina no carimbo
    `t_k`. Se a luz acendeu em `t_on` dentro dessa janela, a fração do tempo de
    exposição com luz acesa é `(t_k − t_on)/T_exp`, e é exatamente essa fração
    que aparece no brilho normalizado. Daí `t_on = t_k − fração · T_exp`, o que
    leva a incerteza de ±1 quadro (16,7 ms a 60 fps) para a casa do
    milissegundo.

    `T_exp` é assumido igual ao período entre quadros quando não informado —
    verdade aproximada com exposição longa (−6 ≈ 1/64 s contra período de
    1/60 s). Com exposição curta a fração satura e a interpolação simplesmente
    não dispara, em vez de mentir.
    """
    brilhos = [q.get("brilho_roi") for q in quadros]
    if any(b is None for b in brilhos) or len(brilhos) < 5:
        return {"detectado": False, "motivo": "sem ROI ou quadros insuficientes"}

    valores = np.asarray(brilhos, dtype=float)
    baixo = float(np.percentile(valores, 10))
    alto = float(np.percentile(valores, 90))
    amplitude = alto - baixo

    if amplitude < degrau_min:
        return {
            "detectado": False,
            "motivo": f"amplitude {amplitude:.1f} < mínimo {degrau_min}",
            "amplitude": round(amplitude, 3),
        }

    # Trabalha sempre no sentido "subindo": se a luz apagou, inverte o sinal e
    # devolve a mesma lógica, em vez de duplicar o código com sinais trocados.
    subindo = float(np.median(valores[-3:])) >= float(np.median(valores[:3]))
    sinal = valores if subindo else (baixo + alto) - valores

    acima = np.where(sinal >= baixo + 0.95 * amplitude)[0]
    if len(acima) == 0:
        return {"detectado": False, "motivo": "nenhum quadro atinge o patamar alto"}

    fim = int(acima[0])
    if fim == 0:
        return {
            "detectado": False,
            "motivo": "a transição é anterior ao primeiro quadro registrado",
        }

    candidato = fim - 1
    fracao = float((sinal[candidato] - baixo) / amplitude)

    resultado: dict[str, Any] = {
        "detectado": True,
        "sentido": "acendeu" if subindo else "apagou",
        "brilho_patamar_baixo": round(baixo, 3),
        "brilho_patamar_alto": round(alto, 3),
        "amplitude": round(amplitude, 3),
        "interpolado": False,
    }

    if 0.05 < fracao < 0.95:
        # O quadro `candidato` pegou a transição no meio da exposição.
        periodo_ns = (
            quadros[candidato]["monotonic_ns"] - quadros[candidato - 1]["monotonic_ns"]
            if candidato > 0
            else quadros[fim]["monotonic_ns"] - quadros[candidato]["monotonic_ns"]
        )
        exposicao = exposicao_ns if exposicao_ns is not None else periodo_ns
        resultado.update({
            "quadro_antes": quadros[candidato - 1]["i"] if candidato > 0 else None,
            "quadro_transicao": quadros[candidato]["i"],
            "quadro_depois": quadros[fim]["i"],
            "interpolado": True,
            "fracao_exposicao": round(fracao, 4),
            "exposicao_assumida_ns": int(exposicao),
            "monotonic_ns": int(quadros[candidato]["monotonic_ns"] - fracao * exposicao),
            # Domina o erro de conhecer T_exp, não a resolução do brilho.
            "incerteza_ms_estimada": round(periodo_ns / 1e6 * 0.1, 3),
        })
    else:
        # Sem quadro intermediário: a transição caiu entre dois carimbos e a
        # incerteza é o período inteiro. Melhor dizer isso que fabricar precisão.
        periodo_ns = quadros[fim]["monotonic_ns"] - quadros[candidato]["monotonic_ns"]
        resultado.update({
            "quadro_antes": quadros[candidato]["i"],
            "quadro_depois": quadros[fim]["i"],
            "monotonic_ns": quadros[fim]["monotonic_ns"],
            "incerteza_ms_estimada": round(periodo_ns / 1e6, 3),
        })
    return resultado


def _qualidade_sincronismo(
    evento: dict[str, Any], marcador: dict[str, Any] | None, latencia_ms: float | None
) -> dict[str, Any]:
    """Declara honestamente o que o sincronismo desta sessão vale."""
    if evento.get("detectado"):
        if evento.get("interpolado"):
            nivel, incerteza = "fina", evento.get("incerteza_ms_estimada", 2.0)
        else:
            nivel, incerteza = "um_quadro", evento.get("incerteza_ms_estimada", 16.7)
        base = (
            "evento luminoso físico no quadro; o instante vem da própria imagem, "
            "não de um relógio de software"
        )
    elif marcador is not None:
        nivel, incerteza, base = "grosseira", None, (
            "apenas marcador de clique. Entre o clique e o primeiro disparo do "
            "pulser há latência do software proprietário, não medida aqui. Serve "
            "para alinhar trechos, NÃO para associar pose a A-scan individual."
        )
    else:
        nivel, incerteza, base = "ausente", None, "nenhum evento comum registrado"

    resultado: dict[str, Any] = {
        "nivel": nivel,
        "base": base,
        "incerteza_ms_estimada": incerteza,
        "latencia_pipeline_compensada": latencia_ms is not None,
    }
    if latencia_ms is None:
        resultado["aviso_latencia"] = (
            "latência do pipeline da câmera não medida nesta montagem. O carimbo "
            "é do instante de entrega pelo USB, não da exposição do sensor. "
            "Rode medir_latencia.py e passe o valor."
        )
    return resultado


def salvar_metadados(
    caminho: Path,
    *,
    sessao_id: str,
    video: Path,
    gravacao: Gravacao,
    fonte: FonteCamera,
    perfil: dict[str, Any] | None,
    marcador: dict[str, Any] | None,
    latencia_ms: float | None,
    roi_evento: tuple[int, int, int, int] | None,
    notas: str = "",
) -> dict[str, Any]:
    evento = (
        detectar_evento_luminoso(gravacao.quadros)
        if roi_evento is not None
        else {"detectado": False, "motivo": "ROI de evento não configurada"}
    )

    documento = {
        "schema": SCHEMA,
        "sessao_id": sessao_id,
        "gerado_em": _agora(),
        "notas_do_operador": notas,
        "video": {
            "arquivo": video.name,
            "sha256": _sha256(video) if video.exists() else None,
            "tamanho_bytes": video.stat().st_size if video.exists() else None,
            "codec": gravacao.codec,
            "n_quadros_na_tabela": len(gravacao.quadros),
            "n_quadros_escritos": gravacao.n_escritos,
            "descartados_por_fila": gravacao.descartados_por_fila,
        },
        "calibracao": perfil,
        "camera": fonte.diagnostico(),
        "sincronismo": {
            "qualidade": _qualidade_sincronismo(evento, marcador, latencia_ms),
            "marcador_clique": marcador,
            "evento_luminoso": evento,
            "latencia_pipeline_ms": latencia_ms,
            "roi_evento": list(roi_evento) if roi_evento else None,
        },
        "quadros": gravacao.quadros,
        "limitacoes": [
            "O carimbo de cada quadro é o instante de entrega pelo driver, não o "
            "instante de exposição do sensor. A diferença é a latência de "
            "pipeline; meça com medir_latencia.py e informe o valor.",
            "O marcador de clique não é o início da aquisição de ultrassom: é o "
            "início do processamento do clique pelo software proprietário.",
            "Nenhum número aqui é métrico. Converter pixel em milímetro exige o "
            "perfil de calibração e, para o tanque, a calibração refrativa.",
        ],
    }

    # Alertas de foco sobem para o topo das limitações: são a diferença entre
    # "K vale aqui" e "K foi medido em outra condição".
    for alerta in documento["camera"].get("foco_contra_calibracao", {}).get("alertas", []):
        documento["limitacoes"].insert(0, f"FOCO: {alerta}")

    if len(gravacao.quadros) != gravacao.n_escritos:
        documento["limitacoes"].insert(
            0,
            f"ATENÇÃO: {len(gravacao.quadros)} quadros na tabela e "
            f"{gravacao.n_escritos} escritos no vídeo. A correspondência "
            "índice↔carimbo está quebrada; não use esta sessão.",
        )

    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(documento, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return documento


def carregar_perfil_para_sessao(caminho: Path | None) -> dict[str, Any] | None:
    """Lê o perfil de calibração e registra o estado da transferência.

    Não recusa perfil `nao_validada` — gravar vídeo não exige calibração
    validada. Mas o estado viaja dentro dos metadados, para que qualquer
    processamento posterior saiba sobre o que está apoiado.
    """
    if caminho is None:
        return None
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroSessao(f"perfil de calibração não encontrado: {caminho}")

    import sys

    raiz = caminho.resolve().parent.parent
    sys.path.insert(0, str(raiz / "calibracao"))
    from caliscope_import import carregar_perfil_ativo  # noqa: PLC0415

    dados = carregar_perfil_ativo(caminho, exigir_transferencia=False)
    return {
        "perfil": str(caminho),
        "camera_key": dados["camera_key"],
        "image_size": dados["image_size"],
        "K": dados["K"],
        "dist": dados["dist"],
        "focus_esperado": dados["focus_esperado"],
        "import_id": dados["import_id"],
        "activation_id": dados["activation_id"],
        "transferencia": dados["transferencia"]["status"],
        "aviso": (
            None
            if dados["transferencia"]["status"] == "validada"
            else "transferência ainda não validada nesta bancada; "
                 "nenhum número métrico derivado desta sessão é defensável"
        ),
    }


def novo_id_sessao() -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.localtime())
