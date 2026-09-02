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

SCHEMA = {"name": "pose.sessao_aquisicao", "version": 2}

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
    a captura continua e a fila cresce: perder quadro por I/O seria perder
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
        self._lock = threading.Lock()
        self._erro_escrita: str | None = None
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
        try:
            self._fila.put_nowait(quadro.imagem)
        except queue.Full:
            # O descarte é contabilizado, mas o registro não entra na tabela:
            # assim índice de vídeo e carimbo continuam correspondendo 1:1.
            with self._lock:
                self.descartados_por_fila += 1
            return

        with self._lock:
            registro = {
                "i": len(self.quadros),
                "indice_fonte": quadro.indice,
                "monotonic_ns": quadro.monotonic_ns,
            }
            if quadro.brilho_roi is not None:
                registro["brilho_roi"] = round(quadro.brilho_roi, 3)
            self.quadros.append(registro)

    def encerrar(self) -> None:
        if self._thread is not None:
            self._fila.put(None)
            self._thread.join(timeout=30.0)
            if self._thread.is_alive():
                raise ErroSessao(
                    "a fila de vídeo não terminou em 30 s; o arquivo foi preservado "
                    "para recuperação e não deve ser considerado completo"
                )
            self._thread = None
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        if self._erro_escrita is not None:
            raise ErroSessao(f"falha ao escrever o vídeo: {self._erro_escrita}")

    def _laco(self) -> None:
        while True:
            imagem = self._fila.get()
            if imagem is None:
                return
            if self._writer is not None and self._erro_escrita is None:
                try:
                    self._writer.write(imagem)
                    with self._lock:
                        self._n_escritos += 1
                except Exception as exc:  # noqa: BLE001
                    # Continua drenando a fila para que encerrar() nunca fique
                    # bloqueado tentando inserir o sentinela numa fila cheia.
                    self._erro_escrita = repr(exc)

    @property
    def n_escritos(self) -> int:
        with self._lock:
            return self._n_escritos

    def snapshot_quadros(self) -> list[dict[str, Any]]:
        """Cópia consistente da tabela para UI e serialização."""
        with self._lock:
            return [dict(quadro) for quadro in self.quadros]

    def quadro_mais_proximo(self, monotonic_ns: int) -> tuple[dict[str, Any] | None, float]:
        """Retorna o quadro gravado mais próximo e a diferença marcador−quadro."""
        quadros = self.snapshot_quadros()
        if not quadros:
            return None, float("nan")
        melhor = min(quadros, key=lambda q: abs(q["monotonic_ns"] - monotonic_ns))
        return melhor, (monotonic_ns - melhor["monotonic_ns"]) / 1e6

    def telemetria(self) -> dict[str, Any]:
        """Resumo barato e thread-safe para a barra de saúde da interface."""
        with self._lock:
            primeiro = self.quadros[0]["monotonic_ns"] if self.quadros else None
            ultimo = self.quadros[-1]["monotonic_ns"] if self.quadros else None
            recebidos = len(self.quadros)
            escritos = self._n_escritos
            descartados = self.descartados_por_fila
        return {
            "n_quadros_recebidos": recebidos,
            "n_quadros_escritos": escritos,
            "duracao_s": (
                round((ultimo - primeiro) / 1e9, 3)
                if primeiro is not None and ultimo is not None else 0.0
            ),
            "fila_atual": self._fila.qsize(),
            "fila_limite": self._fila.maxsize,
            "descartados_por_fila": descartados,
            "erro_escrita": self._erro_escrita,
        }


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
    leva a incerteza de ±1 quadro (um período, ~48 ms a 21 fps) para a casa do
    milissegundo.

    `T_exp` é assumido igual ao período entre quadros quando não informado:
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


def resumir_pre_roll(
    quadros: list[dict[str, Any]], marcador: dict[str, Any] | None
) -> dict[str, Any]:
    """Descreve os quadros realmente escritos antes do marcador de clique."""
    if marcador is None:
        return {
            "presente": False,
            "duracao_ms": None,
            "n_quadros_antes_do_marcador": 0,
            "motivo": "marcador de clique não registrado",
        }
    if not quadros:
        return {
            "presente": False,
            "duracao_ms": 0.0,
            "n_quadros_antes_do_marcador": 0,
            "motivo": "nenhum quadro escrito antes do marcador",
        }

    instante = int(marcador["monotonic_ns"])
    anteriores = [q for q in quadros if int(q["monotonic_ns"]) < instante]
    inicio = int(quadros[0]["monotonic_ns"])
    return {
        "presente": bool(anteriores),
        "inicio_monotonic_ns": inicio,
        "marcador_monotonic_ns": instante,
        "duracao_ms": round(max(0, instante - inicio) / 1e6, 3),
        "n_quadros_antes_do_marcador": len(anteriores),
        "nota": (
            "o escritor foi aberto e assinou a fonte antes de o listener global "
            "ser ativado; estes quadros são pré-roll real no próprio vídeo"
        ),
    }


def _escrever_json_atomico(caminho: Path, documento: dict[str, Any]) -> None:
    """Publica JSON completo de uma vez; nunca expõe metade do documento final."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(
        json.dumps(documento, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporario.replace(caminho)


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
    quadros = gravacao.snapshot_quadros()
    evento = (
        detectar_evento_luminoso(quadros)
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
            "n_quadros_na_tabela": len(quadros),
            "n_quadros_escritos": gravacao.n_escritos,
            "descartados_por_fila": gravacao.descartados_por_fila,
            "pre_roll": resumir_pre_roll(quadros, marcador),
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
        "quadros": quadros,
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

    if len(quadros) != gravacao.n_escritos:
        documento["limitacoes"].insert(
            0,
            f"ATENÇÃO: {len(quadros)} quadros na tabela e "
            f"{gravacao.n_escritos} escritos no vídeo. A correspondência "
            "índice↔carimbo está quebrada; não use esta sessão.",
        )

    _escrever_json_atomico(Path(caminho), documento)
    return documento


def salvar_manifesto_incompleto(
    caminho: Path, *, sessao_id: str, video: Path, erro: str
) -> Path:
    """Best effort de recuperação quando a finalização completa falha."""
    manifesto = Path(caminho).with_name(f"sessao_{sessao_id}.incompleta.json")
    documento = {
        "schema": SCHEMA,
        "sessao_id": sessao_id,
        "gerado_em": _agora(),
        "estado": "incompleta",
        "erro_finalizacao": erro,
        "video": {
            "arquivo": Path(video).name,
            "preservado": Path(video).exists(),
            "tamanho_bytes": Path(video).stat().st_size if Path(video).exists() else None,
        },
        "nota": (
            "A finalização completa falhou. O vídeo foi preservado deliberadamente; "
            "este manifesto não autoriza uso científico da sessão."
        ),
    }
    _escrever_json_atomico(manifesto, documento)
    return manifesto


def _carregar_foco_referencia(
    caminho_perfil: Path, camera_key: str
) -> dict[str, Any] | None:
    """Lê o sidecar de foco de referência ao lado do perfil selado.

    O perfil ativo é selado por digest: acrescentar um campo nele quebraria o
    selo. O foco de referência mora num arquivo próprio, não selado, com a
    proveniência declarada — inclusive quando ela é uma assunção, e não uma
    leitura feita durante a captura da calibração.
    """
    sidecar = caminho_perfil.with_suffix(".foco.json")
    if not sidecar.exists():
        return None
    dados = json.loads(sidecar.read_text(encoding="utf-8"))
    schema = dados.get("schema", {})
    if schema.get("name") != "pose.foco_referencia":
        raise ErroSessao(f"{sidecar} não é um sidecar de foco de referência")
    if dados.get("camera_key") != camera_key:
        raise ErroSessao(
            f"sidecar de foco é da câmera {dados.get('camera_key')!r}, "
            f"perfil é {camera_key!r}"
        )
    return dados


def carregar_perfil_para_sessao(caminho: Path | None) -> dict[str, Any] | None:
    """Lê o perfil de calibração e registra o estado da transferência.

    Não recusa perfil `nao_validada`: gravar vídeo não exige calibração
    validada. Mas o estado viaja dentro dos metadados, para que qualquer
    processamento posterior saiba sobre o que está apoiado.
    """
    if caminho is None:
        return None
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroSessao(f"perfil de calibração não encontrado: {caminho}")

    import sys

    raiz_calibracao = caminho.resolve().parent.parent
    sys.path.insert(0, str(raiz_calibracao))
    from caliscope_import import carregar_perfil_ativo  # noqa: PLC0415

    dados = carregar_perfil_ativo(caminho, exigir_transferencia=False)

    # Foco de referência: primeiro o que estiver dentro do perfil selado; na
    # falta dele, o sidecar. A origem viaja no JSON da sessão.
    focus_esperado = dados["focus_esperado"]
    focus_origem = "perfil" if focus_esperado is not None else None
    focus_proveniencia: dict[str, Any] | None = None
    if focus_esperado is None:
        sidecar = _carregar_foco_referencia(caminho, dados["camera_key"])
        if sidecar is not None:
            focus_esperado = sidecar.get("focus_esperado")
            focus_origem = "sidecar"
            focus_proveniencia = sidecar.get("proveniencia")

    return {
        "perfil": str(caminho),
        "camera_key": dados["camera_key"],
        "image_size": dados["image_size"],
        "K": dados["K"],
        "dist": dados["dist"],
        "focus_esperado": focus_esperado,
        "focus_esperado_origem": focus_origem,
        "focus_esperado_proveniencia": focus_proveniencia,
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
    # Milissegundos evitam colisão ao desarmar e rearmar dentro do mesmo segundo.
    return (
        time.strftime("%Y%m%d_%H%M%S", time.localtime())
        + f"_{(time.time_ns() // 1_000_000) % 1000:03d}"
    )
