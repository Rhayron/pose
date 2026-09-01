"""Gate de transferencia: o intrinseco ativo ainda descreve ESTA bancada?

Por que este arquivo existe
---------------------------
O K da S600 foi medido nesta bancada em 2026-09-01 (3840x2160). Isso nao
congela a geometria para sempre. Sem deixar rastro no camera_array.toml
podem mudar:

* o foco (o driver frequentemente ignora CAP_PROP_AUTOFOCUS=0);
* o campo de visao (FOV ajustavel 40-73 graus);
* a resolucao efetivamente negociada pelo DirectShow.

Qualquer um dos tres muda fx, fy, cx, cy. A pergunta "o K ainda vale?"
so tem uma resposta honesta: medir.

Hipotese testada
----------------
    H0: o par (K, dist) do perfil ativo descreve a camera agora.

Procedimento
------------
1. Capture N >= 10 vistas do tabuleiro ChArUco padrao, em 3840x2160, cobrindo
   centro, bordas e cantos, com inclinacoes variadas.
2. Para cada vista, estima-se a pose por `solvePnP` com **K e dist congelados**.
   Nao ha reajuste. Se K estivesse errado, o erro apareceria como residuo — que
   e exatamente o que se quer observar.
3. Mede-se o residuo de reprojecao de cada canto.

Criterios pre-registrados (fixados antes da primeira medicao)
--------------------------------------------------------------
    n_vistas_min          >= 10
    erro_mediano_px       <= 0.60
    erro_p90_px           <= 1.20
    erro_max_px           <= 3.00
    frac_acima_1px        <= 0.20
    escala_fx_refit        em [0.98, 1.02]

Base dos numeros — nenhum foi inventado para caber no resultado:

* 0,60 px e o `erro_mediano_holdout_px_max` que o proprio pose ja usava como
  criterio pre-registrado do calibrador interno;
* 1,20 px e o dobro, seguindo a mesma razao P90/mediana que o pose ja adotava
  (1,00 / 0,50);
* a S600 foi calibrada pelo Caliscope com RMSE 0,533 px. Uma transferencia
  valida nao pode sair muito pior que a calibracao de origem;
* a janela de 2% em `escala_fx_refit` e a mesma tolerancia de
  `largura_relativa_ic95_fx_max` ja pre-registrada no projeto.

Por que `escala_fx_refit` nao e opcional
----------------------------------------
Erro de reprojecao sozinho **nao detecta** distancia focal errada. O `solvePnP`
absorve um erro de escala em fx no eixo de profundidade: com fx 5% maior, ele
simplesmente estima o tabuleiro 5% mais longe e o residuo continua baixo.

Isso foi medido, nao suposto. Em `teste_caliscope.py`, com fx deliberadamente
5% errado, o gate mediu:

    erro mediano  0,171 px   (limite 0,60)  -> passaria
    erro P90      0,483 px   (limite 1,20)  -> passaria
    escala_fx     1,0496                    -> REPROVA

Um gate que so olhasse residuo teria aprovado um foco 5% errado — e o pose
mede pose 6DoF de um transdutor, entao 5% de erro de escala vira 5% de erro de
distancia direto no resultado. `escala_fx_refit` e o criterio que faz o
trabalho aqui; os limites de residuo pegam o resto (nitidez, deteccao ruim,
tabuleiro nao planar).

O diagnostico reajusta **apenas** um fator de escala global sobre fx/fy e
reporta a razao, separando as duas maneiras de falhar: erro sem estrutura
(ruido, deteccao) versus escala sistematica (foco ou FOV mudaram). O valor
reajustado e **relatado, nunca gravado** — se a escala saiu da janela, o
caminho e recalibrar no Caliscope, nao remendar o K importado por esse fator.

Uso
---
    python validar_transferencia.py --perfil perfis_ativos/s600.json \\
        --capturas capturas_validacao/ --output rig/transferencia.json

    python validar_transferencia.py ... --registrar   # grava no perfil ativo
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from caliscope_import import (
    CaliscopeImportError,
    carregar_perfil_ativo,
    registrar_transferencia,
)

RAIZ = Path(__file__).resolve().parent

CRITERIOS: dict[str, Any] = {
    "n_vistas_min": 10,
    "n_cantos_por_vista_min": 12,
    "erro_mediano_px_max": 0.60,
    "erro_p90_px_max": 1.20,
    "erro_max_px_max": 3.00,
    "frac_acima_1px_max": 0.20,
    "escala_fx_refit_min": 0.98,
    "escala_fx_refit_max": 1.02,
    "base": (
        "0,60 px e 2% herdados dos criterios pre-registrados do calibrador "
        "interno do pose; a origem Caliscope mediu RMSE 0,533 px na S600."
    ),
}

_DICIONARIOS = {
    "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
    "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
    "DICT_4X4_250": cv2.aruco.DICT_4X4_250,
    "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
    "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
    "DICT_6X6_250": cv2.aruco.DICT_6X6_250,
}


def _construir_tabuleiro(contrato: dict[str, Any]):
    nome = str(contrato["dicionario"])
    if nome not in _DICIONARIOS:
        raise CaliscopeImportError(f"dicionario ArUco desconhecido: {nome}")
    dicionario = cv2.aruco.getPredefinedDictionary(_DICIONARIOS[nome])

    # Escala real medida com paquimetro, nao a nominal impressa. O marcador
    # e escalado pela mesma razao para preservar a proporcao do PDF gerado.
    quadrado_mm = float(contrato["square_mm_medido"])
    razao = float(contrato["marker_mm_nominal"]) / float(contrato["square_mm_nominal"])
    marcador_mm = quadrado_mm * razao

    tabuleiro = cv2.aruco.CharucoBoard(
        (int(contrato["squares_x"]), int(contrato["squares_y"])),
        quadrado_mm, marcador_mm, dicionario,
    )
    tabuleiro.setLegacyPattern(bool(contrato.get("legacy_pattern", False)))
    return tabuleiro, dicionario, quadrado_mm, marcador_mm


def _detectar(imagem: np.ndarray, tabuleiro, dicionario):
    """Deteccao ChArUco com refinamento subpixel.

    `interpolateCornersCharuco` foi removida no OpenCV 4.13; `CharucoDetector`
    e a API atual. O fallback mantem o script utilizavel em ambientes com
    OpenCV mais antigo, sem mudar o resultado.
    """
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY) if imagem.ndim == 3 else imagem

    parametros = cv2.aruco.DetectorParameters()
    parametros.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX

    if hasattr(cv2.aruco, "CharucoDetector"):
        detector = cv2.aruco.CharucoDetector(tabuleiro)
        detector.setDetectorParameters(parametros)
        cantos_ch, ids_ch, _cantos, _ids = detector.detectBoard(cinza)
        if ids_ch is None or len(ids_ch) < 4:
            return None, None
        return cantos_ch, ids_ch

    cantos, ids, _ = cv2.aruco.ArucoDetector(dicionario, parametros).detectMarkers(cinza)
    if ids is None or len(ids) == 0:
        return None, None
    n, cantos_ch, ids_ch = cv2.aruco.interpolateCornersCharuco(  # type: ignore[attr-defined]
        cantos, ids, cinza, tabuleiro
    )
    if n is None or n < 4:
        return None, None
    return cantos_ch, ids_ch


def _medir_vista(
    cantos_ch: np.ndarray, ids_ch: np.ndarray, tabuleiro,
    K: np.ndarray, dist: np.ndarray,
) -> dict[str, Any] | None:
    """Pose por PnP com K congelado; devolve os residuos de reprojecao."""
    objeto = tabuleiro.getChessboardCorners()[ids_ch.flatten()].astype(np.float64)
    imagem = cantos_ch.reshape(-1, 2).astype(np.float64)
    if len(objeto) < 4:
        return None

    ok, rvec, tvec = cv2.solvePnP(
        objeto, imagem, K, dist, flags=cv2.SOLVEPNP_ITERATIVE
    )
    if not ok:
        return None
    rvec, tvec = cv2.solvePnPRefineLM(objeto, imagem, K, dist, rvec, tvec)

    projetado, _ = cv2.projectPoints(objeto, rvec, tvec, K, dist)
    residuos = np.linalg.norm(projetado.reshape(-1, 2) - imagem, axis=1)

    R, _ = cv2.Rodrigues(rvec)
    tilt = float(np.degrees(np.arccos(np.clip(abs(R[2, 2]), -1.0, 1.0))))

    return {
        "n_cantos": int(len(objeto)),
        "residuos": residuos,
        "objeto": objeto,
        "imagem": imagem,
        "rvec": rvec,
        "tvec": tvec,
        "tilt_graus": round(tilt, 1),
        "distancia_mm": round(float(np.linalg.norm(tvec)), 1),
        "erro_mediano_px": round(float(np.median(residuos)), 4),
        "erro_p90_px": round(float(np.percentile(residuos, 90)), 4),
        "erro_max_px": round(float(residuos.max()), 4),
    }


def _escala_refit(vistas: list[dict[str, Any]], K: np.ndarray, dist: np.ndarray) -> float:
    """Ajusta UM fator de escala global sobre fx/fy e devolve a razao.

    Diagnostico puro: separa erro sem estrutura de erro sistematico de escala.
    O valor nunca substitui o K importado.
    """
    def custo(s: float) -> float:
        Ks = K.copy()
        Ks[0, 0] *= s
        Ks[1, 1] *= s
        total: list[float] = []
        for v in vistas:
            ok, rvec, tvec = cv2.solvePnP(
                v["objeto"], v["imagem"], Ks, dist, flags=cv2.SOLVEPNP_ITERATIVE
            )
            if not ok:
                return float("inf")
            proj, _ = cv2.projectPoints(v["objeto"], rvec, tvec, Ks, dist)
            total.extend(np.linalg.norm(proj.reshape(-1, 2) - v["imagem"], axis=1))
        return float(np.median(total)) if total else float("inf")

    # Busca ternaria: o custo e unimodal em s numa janela estreita.
    lo, hi = 0.85, 1.15
    for _ in range(40):
        a = lo + (hi - lo) / 3.0
        b = hi - (hi - lo) / 3.0
        if custo(a) < custo(b):
            hi = b
        else:
            lo = a
    return round((lo + hi) / 2.0, 5)


def validar(perfil_path: Path, capturas: Path) -> dict[str, Any]:
    perfil = carregar_perfil_ativo(perfil_path, exigir_transferencia=False)
    K = np.array(perfil["K"], dtype=np.float64)
    dist = np.array(perfil["dist"], dtype=np.float64).reshape(1, -1)
    largura, altura = perfil["image_size"]

    raw = json.loads(Path(perfil_path).read_text(encoding="utf-8"))
    contrato = raw["import_document"]["profile"]["charuco"]["contract"]
    tabuleiro, dicionario, quadrado_mm, marcador_mm = _construir_tabuleiro(contrato)

    arquivos = sorted(
        p for p in Path(capturas).iterdir()
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp")
    )
    if not arquivos:
        raise CaliscopeImportError(f"nenhuma imagem em {capturas}")

    vistas: list[dict[str, Any]] = []
    por_vista: list[dict[str, Any]] = []
    descartadas: list[dict[str, str]] = []

    for arquivo in arquivos:
        imagem = cv2.imread(str(arquivo))
        if imagem is None:
            descartadas.append({"arquivo": arquivo.name, "motivo": "ilegivel"})
            continue
        h, w = imagem.shape[:2]
        if (w, h) != (largura, altura):
            # Falha dura, nao aviso: um intrinseco nao vale em outra resolucao,
            # e reescalar K silenciosamente e como o erro entra sem ser visto.
            raise CaliscopeImportError(
                f"{arquivo.name} tem {w}x{h}, mas o perfil vale para "
                f"{largura}x{altura}. Recapture no modo certo; nao ha reescala."
            )
        cantos_ch, ids_ch = _detectar(imagem, tabuleiro, dicionario)
        if cantos_ch is None:
            descartadas.append({"arquivo": arquivo.name, "motivo": "sem tabuleiro"})
            continue
        medida = _medir_vista(cantos_ch, ids_ch, tabuleiro, K, dist)
        if medida is None:
            descartadas.append({"arquivo": arquivo.name, "motivo": "PnP falhou"})
            continue
        if medida["n_cantos"] < CRITERIOS["n_cantos_por_vista_min"]:
            descartadas.append({
                "arquivo": arquivo.name,
                "motivo": f"apenas {medida['n_cantos']} cantos",
            })
            continue
        vistas.append(medida)
        por_vista.append({
            "arquivo": arquivo.name,
            **{k: medida[k] for k in (
                "n_cantos", "tilt_graus", "distancia_mm",
                "erro_mediano_px", "erro_p90_px", "erro_max_px")},
        })

    if not vistas:
        raise CaliscopeImportError(
            "nenhuma vista utilizavel. Verifique iluminacao, foco e se o "
            "tabuleiro impresso e o mesmo do contrato."
        )

    todos = np.concatenate([v["residuos"] for v in vistas])
    escala = _escala_refit(vistas, K, dist)

    medidas = {
        "n_vistas": len(vistas),
        "n_cantos_total": int(len(todos)),
        "erro_mediano_px": round(float(np.median(todos)), 4),
        "erro_p90_px": round(float(np.percentile(todos, 90)), 4),
        "erro_p99_px": round(float(np.percentile(todos, 99)), 4),
        "erro_max_px": round(float(todos.max()), 4),
        "rms_px": round(float(np.sqrt(np.mean(todos ** 2))), 4),
        "frac_acima_1px": round(float((todos > 1.0).mean()), 4),
        "escala_fx_refit": escala,
    }

    veredicto = {
        "n_vistas_min": {
            "aprovado": medidas["n_vistas"] >= CRITERIOS["n_vistas_min"],
            "medido": f"{medidas['n_vistas']} >= {CRITERIOS['n_vistas_min']}",
        },
        "erro_mediano_px_max": {
            "aprovado": medidas["erro_mediano_px"] <= CRITERIOS["erro_mediano_px_max"],
            "medido": f"{medidas['erro_mediano_px']} <= {CRITERIOS['erro_mediano_px_max']}",
        },
        "erro_p90_px_max": {
            "aprovado": medidas["erro_p90_px"] <= CRITERIOS["erro_p90_px_max"],
            "medido": f"{medidas['erro_p90_px']} <= {CRITERIOS['erro_p90_px_max']}",
        },
        "erro_max_px_max": {
            "aprovado": medidas["erro_max_px"] <= CRITERIOS["erro_max_px_max"],
            "medido": f"{medidas['erro_max_px']} <= {CRITERIOS['erro_max_px_max']}",
        },
        "frac_acima_1px_max": {
            "aprovado": medidas["frac_acima_1px"] <= CRITERIOS["frac_acima_1px_max"],
            "medido": f"{medidas['frac_acima_1px']} <= {CRITERIOS['frac_acima_1px_max']}",
        },
        "escala_fx_refit": {
            "aprovado": (CRITERIOS["escala_fx_refit_min"] <= escala
                         <= CRITERIOS["escala_fx_refit_max"]),
            "medido": (f"{escala} em [{CRITERIOS['escala_fx_refit_min']}, "
                       f"{CRITERIOS['escala_fx_refit_max']}]"),
        },
    }
    aprovado = all(item["aprovado"] for item in veredicto.values())

    interpretacao: list[str] = []
    if not veredicto["escala_fx_refit"]["aprovado"]:
        direcao = "maior" if escala > 1 else "menor"
        interpretacao.append(
            f"escala sistematica de {(escala - 1) * 100:+.2f}%: a distancia focal "
            f"real e {direcao} que a importada. Causa provavel: foco ou ajuste de "
            "FOV da S600 mudaram entre os dois projetos. Recalibre no Caliscope; "
            "nao corrija o K importado por este fator."
        )
    if aprovado:
        interpretacao.append(
            "residuos compativeis com a calibracao de origem (RMSE 0,533 px). "
            "H0 nao foi rejeitada: o intrinseco importado descreve esta bancada."
        )
    elif veredicto["escala_fx_refit"]["aprovado"]:
        interpretacao.append(
            "sem escala sistematica, mas residuos altos. Erro provavelmente nao "
            "esta em fx/fy: verifique nitidez, iluminacao, planaridade do "
            "tabuleiro impresso e se ele e o mesmo do contrato."
        )

    return {
        "schema": {"name": "pose.transferencia_intrinseca", "version": 1},
        "perfil": str(perfil_path),
        "import_id": perfil["import_id"],
        "activation_id": perfil["activation_id"],
        "camera_key": perfil["camera_key"],
        "hipotese": "H0: o (K, dist) importado descreve a camera nesta bancada",
        "metodo": "solvePnP com K e dist congelados; sem reajuste de intrinsecos",
        "image_size": [largura, altura],
        "tabuleiro": {
            "contrato": contrato,
            "quadrado_mm": quadrado_mm,
            "marcador_mm": round(marcador_mm, 4),
        },
        "criterios_pre_registrados": CRITERIOS,
        "medidas": medidas,
        "veredicto": veredicto,
        "aprovado": aprovado,
        "interpretacao": interpretacao,
        "por_vista": por_vista,
        "descartadas": descartadas,
        "ambiente": {
            "opencv": cv2.__version__,
            "numpy": np.__version__,
            "python": sys.version.split()[0],
        },
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--perfil", default="perfis_ativos/s600.json")
    ap.add_argument("--capturas", required=True,
                    help="pasta com as vistas ChArUco na resolucao do perfil")
    ap.add_argument("--output", default="rig/transferencia.json")
    ap.add_argument("--registrar", action="store_true",
                    help="grava o resultado dentro do perfil ativo")

    args = ap.parse_args(argv)
    perfil = Path(args.perfil)
    perfil = perfil if perfil.is_absolute() else RAIZ / perfil
    capturas = Path(args.capturas)
    capturas = capturas if capturas.is_absolute() else RAIZ / capturas
    saida = Path(args.output)
    saida = saida if saida.is_absolute() else RAIZ / saida

    try:
        relatorio = validar(perfil, capturas)
    except (CaliscopeImportError, OSError, ValueError, cv2.error) as exc:
        json.dump({"ok": False, "erro": type(exc).__name__, "mensagem": str(exc)},
                  sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 2

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(
        json.dumps(relatorio, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    resumo: dict[str, Any] = {
        "ok": True,
        "aprovado": relatorio["aprovado"],
        "output": str(saida),
        "medidas": relatorio["medidas"],
        "veredicto": relatorio["veredicto"],
        "interpretacao": relatorio["interpretacao"],
    }

    if args.registrar:
        evidencia = {
            "relatorio": str(saida),
            "aprovado": relatorio["aprovado"],
            "medidas": relatorio["medidas"],
            "criterios": CRITERIOS,
            "gerado_em": relatorio["gerado_em"],
        }
        resumo["registro"] = registrar_transferencia(perfil, evidencia)

    json.dump(resumo, sys.stdout, indent=2, ensure_ascii=False, allow_nan=False)
    sys.stdout.write("\n")
    return 0 if relatorio["aprovado"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
