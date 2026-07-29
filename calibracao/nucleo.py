"""
Núcleo compartilhado da calibração intrínseca (WP1).

Ponto único de verdade para: parâmetros do tabuleiro, detecção ChArUco,
métricas de nitidez e contabilidade de cobertura. Todos os scripts importam
daqui para que captura e calibração NUNCA usem tabuleiros diferentes — esse
é o erro silencioso mais comum em calibração.

Unidade métrica do projeto: MILÍMETROS. Object points em mm ⇒ tvec em mm.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

# --------------------------------------------------------------------------
# Configuração do tabuleiro (contrato serializado em tabuleiro.json)
# --------------------------------------------------------------------------


@dataclass
class ConfigTabuleiro:
    # DICT_4X4_50 por decisão de projeto: o aparato do tanque já usa 7X7 (ID 0)
    # e 5X5 (ID 3). Um dicionário distinto evita colisão de IDs quando o
    # tabuleiro e a braçadeira aparecerem no mesmo quadro (calibração
    # refrativa, etapa seguinte).
    dicionario: str = "DICT_4X4_50"
    squares_x: int = 7
    squares_y: int = 5
    square_mm_nominal: float = 35.0
    marker_mm_nominal: float = 26.0
    # Preenchido À MÃO pelo usuário após imprimir e medir com paquímetro.
    # É o ÚNICO número que define a escala métrica de todo o projeto.
    square_mm_medido: float | None = None
    legacy_pattern: bool = False
    gerado_em: str = ""
    opencv: str = ""

    def salvar(self, caminho: Path) -> None:
        caminho.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def carregar(caminho: Path) -> "ConfigTabuleiro":
        if not caminho.exists():
            raise SystemExit(
                f"[erro] {caminho} não existe. Rode primeiro: python gerar_tabuleiro.py"
            )
        return ConfigTabuleiro(**json.loads(caminho.read_text(encoding="utf-8")))


def dicionario_por_nome(nome: str):
    if not hasattr(cv2.aruco, nome):
        raise SystemExit(f"[erro] dicionário ArUco desconhecido nesta build: {nome}")
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, nome))


def escala_efetiva(cfg: ConfigTabuleiro, permitir_nominal: bool = False):
    """Devolve (square_mm, marker_mm, fonte).

    Se a impressora escalou o desenho, quadrado e marcador escalaram juntos —
    por isso o marcador é derivado da razão medida/nominal, não fixado.
    """
    if cfg.square_mm_medido is not None:
        k = cfg.square_mm_medido / cfg.square_mm_nominal
        return cfg.square_mm_medido, cfg.marker_mm_nominal * k, "medido"
    if not permitir_nominal:
        raise SystemExit(
            "[erro] 'square_mm_medido' está null em tabuleiro.json.\n"
            "       Imprima o tabuleiro, meça um quadrado com paquímetro (ou a régua\n"
            "       de 100 mm impressa na folha) e escreva o valor no JSON.\n"
            "       Sem isso a pose sai em unidade arbitrária, não em mm.\n"
            "       (--assumir-nominal força o uso do valor nominal, marcando o\n"
            "        resultado como NÃO RASTREÁVEL.)"
        )
    return cfg.square_mm_nominal, cfg.marker_mm_nominal, "nominal_NAO_RASTREAVEL"


def construir_board(cfg: ConfigTabuleiro, square_mm: float, marker_mm: float):
    dicionario = dicionario_por_nome(cfg.dicionario)
    board = cv2.aruco.CharucoBoard(
        (cfg.squares_x, cfg.squares_y), float(square_mm), float(marker_mm), dicionario
    )
    if cfg.legacy_pattern and hasattr(board, "setLegacyPattern"):
        board.setLegacyPattern(True)
    return board, dicionario


def novo_detector(board):
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 43
    params.adaptiveThreshWinSizeStep = 8
    ch_params = cv2.aruco.CharucoParameters()
    ch_params.tryRefineMarkers = True
    return cv2.aruco.CharucoDetector(
        board, ch_params, params, cv2.aruco.RefineParameters()
    )


def detectar(detector, imagem):
    """Devolve (cantos_charuco Nx1x2 float32, ids Nx1 int32) ou (None, None)."""
    if imagem.ndim == 3:
        cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    else:
        cinza = imagem
    ch_corners, ch_ids, _, _ = detector.detectBoard(cinza)
    if ch_ids is None or len(ch_ids) < 4:
        return None, None
    return np.asarray(ch_corners, np.float32), np.asarray(ch_ids, np.int32)


# --------------------------------------------------------------------------
# Qualidade do quadro
# --------------------------------------------------------------------------


def nitidez_roi(imagem, cantos) -> float:
    """Variância do Laplaciano restrita à região do tabuleiro.

    Medir na imagem inteira mistura o fundo e mede a cena, não o alvo.
    """
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY) if imagem.ndim == 3 else imagem
    p = cantos.reshape(-1, 2)
    x0, y0 = np.floor(p.min(0)).astype(int)
    x1, y1 = np.ceil(p.max(0)).astype(int)
    h, w = cinza.shape[:2]
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, w - 1), min(y1, h - 1)
    if x1 - x0 < 16 or y1 - y0 < 16:
        return 0.0
    return float(cv2.Laplacian(cinza[y0:y1, x0:x1], cv2.CV_64F).var())


def fracao_area(cantos, shape) -> float:
    h, w = shape[:2]
    casco = cv2.convexHull(cantos.reshape(-1, 2).astype(np.float32))
    return float(cv2.contourArea(casco) / (w * h))


def K_provisoria(shape):
    """Intrínsecos GROSSEIROS só para orientar a captura (guia, não medida)."""
    h, w = shape[:2]
    f = 0.9 * max(w, h)
    return np.array([[f, 0, w / 2.0], [0, f, h / 2.0], [0, 0, 1.0]], np.float64)


def inclinacao_graus(board, cantos, ids, shape) -> float:
    """Ângulo entre a normal do tabuleiro e o eixo óptico.

    Usa K provisória: serve para guiar a diversidade de poses na captura.
    NÃO é uma medida — nenhum número deste projeto depende dele.
    """
    objp, imgp = board.matchImagePoints(cantos, ids)
    if objp is None or len(objp) < 6:
        return 0.0
    ok, rvec, _ = cv2.solvePnP(
        objp, imgp, K_provisoria(shape), None, flags=cv2.SOLVEPNP_ITERATIVE
    )
    if not ok:
        return 0.0
    R, _ = cv2.Rodrigues(rvec)
    cos = abs(float(R[2, 2]))
    return float(np.degrees(np.arccos(np.clip(cos, 0.0, 1.0))))


# --------------------------------------------------------------------------
# Cobertura: onde no quadro, em que escala e em que inclinação já medimos
# --------------------------------------------------------------------------

BINS_ESCALA = ((0.00, 0.06, "pequeno"), (0.06, 0.20, "medio"), (0.20, 1.01, "grande"))
BINS_TILT = ((0, 15, "frontal"), (15, 35, "inclinado"), (35, 91, "muito_inclinado"))

# Metas de cobertura — pré-registradas (ver README §Régua).
METAS_COBERTURA = {
    "min_views": 25,
    "celulas_3x3": 9,
    "min_inclinado": 8,        # tilt > 15°
    "min_muito_inclinado": 5,  # tilt > 35°
    "min_por_escala": 4,       # cada bin de escala
}


def _bin(valor, bins):
    for lo, hi, nome in bins:
        if lo <= valor < hi:
            return nome
    return bins[-1][2]


def celulas_tocadas(cantos, shape) -> list[int]:
    """Células da grade 3x3 onde caiu ao menos um CANTO detectado.

    A cobertura que importa para estimar distorção é onde estão os pontos de
    medida, não onde está o centro do alvo. Usar o centroide tornava as
    células dos cantos inalcançáveis em escala média ou grande: para levar o
    centro até lá, metade do tabuleiro teria de sair do quadro.
    """
    h, w = shape[:2]
    p = cantos.reshape(-1, 2)
    col = np.clip((p[:, 0] / (w / 3)).astype(int), 0, 2)
    lin = np.clip((p[:, 1] / (h / 3)).astype(int), 0, 2)
    return sorted(set((lin * 3 + col).tolist()))


def classificar(cantos, shape, tilt):
    h, w = shape[:2]
    cx, cy = cantos.reshape(-1, 2).mean(0)
    celula = int(min(cy / (h / 3), 2)) * 3 + int(min(cx / (w / 3), 2))
    return {
        # `celula` (do centroide) continua sendo a chave do bin de diversidade;
        # `celulas_tocadas` é o que conta para a cobertura do quadro.
        "celula": celula,
        "celulas_tocadas": celulas_tocadas(cantos, shape),
        "escala": _bin(fracao_area(cantos, shape), BINS_ESCALA),
        "tilt": _bin(tilt, BINS_TILT),
    }


def resumo_cobertura(registros):
    celulas = set()
    for r in registros:
        # sessões antigas só têm o centroide; mantém compatibilidade
        celulas.update(r.get("celulas_tocadas") or [r["celula"]])
    escalas = {}
    for r in registros:
        escalas[r["escala"]] = escalas.get(r["escala"], 0) + 1
    n_incl = sum(1 for r in registros if r["tilt"] in ("inclinado", "muito_inclinado"))
    n_muito = sum(1 for r in registros if r["tilt"] == "muito_inclinado")
    return {
        "n_views": len(registros),
        "celulas_cobertas": len(celulas),
        "celulas_faltando": sorted(set(range(9)) - celulas),
        "por_escala": escalas,
        "n_inclinado": n_incl,
        "n_muito_inclinado": n_muito,
    }


def cobertura_atende(resumo) -> tuple[bool, list[str]]:
    m, faltas = METAS_COBERTURA, []
    if resumo["n_views"] < m["min_views"]:
        faltas.append(f"views {resumo['n_views']}/{m['min_views']}")
    if resumo["celulas_cobertas"] < m["celulas_3x3"]:
        faltas.append(f"células {resumo['celulas_cobertas']}/9 (faltam {resumo['celulas_faltando']})")
    if resumo["n_inclinado"] < m["min_inclinado"]:
        faltas.append(f"inclinadas {resumo['n_inclinado']}/{m['min_inclinado']}")
    if resumo["n_muito_inclinado"] < m["min_muito_inclinado"]:
        faltas.append(f"muito inclinadas {resumo['n_muito_inclinado']}/{m['min_muito_inclinado']}")
    for _, _, nome in BINS_ESCALA:
        if resumo["por_escala"].get(nome, 0) < m["min_por_escala"]:
            faltas.append(f"escala {nome} {resumo['por_escala'].get(nome, 0)}/{m['min_por_escala']}")
    return (len(faltas) == 0), faltas


# --------------------------------------------------------------------------
# Procedência
# --------------------------------------------------------------------------


def agora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def sha256_arquivo(caminho: Path, blocos: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(blocos), b""):
            h.update(bloco)
    return h.hexdigest()


def ambiente() -> dict:
    return {
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "python": platform.python_version(),
        "so": f"{platform.system()} {platform.release()}",
        "gerado_em": agora(),
    }
