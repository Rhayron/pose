"""Recusa gravação que não seja o modo do experimento e copia para o Caliscope.

Uso:
    python aceitar_captura.py
    python aceitar_captura.py --fonte caminho.mp4
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MODO = json.loads((RAIZ / "modo_s600.json").read_text(encoding="utf-8"))["mode"]
DESTINO = RAIZ / "caliscope-workspace" / "calibration" / "intrinsic" / "cam_1.mp4"
GRAVACOES = Path.home() / "skelly-cam-recordings"


def _ffprobe(video: Path) -> dict:
    proc = subprocess.run(
        [
            "ffprobe", "-hide_banner", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,avg_frame_rate",
            "-of", "json",
            str(video),
        ],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffprobe falhou: {proc.stderr.strip()}")
    streams = json.loads(proc.stdout).get("streams") or []
    if not streams:
        raise SystemExit(f"{video} não tem stream de vídeo")
    return streams[0]


def _fps(raw: str) -> float:
    if "/" in raw:
        a, b = raw.split("/", 1)
        return float(a) / float(b) if float(b) else 0.0
    return float(raw or 0)


def _mais_recente() -> Path:
    videos = list(GRAVACOES.glob("**/synchronized_videos/*.mp4"))
    if not videos:
        raise SystemExit(f"nenhum MP4 em {GRAVACOES}")
    return max(videos, key=lambda p: p.stat().st_mtime)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fonte", type=Path, default=None)
    args = parser.parse_args()
    fonte = args.fonte or _mais_recente()
    if not fonte.is_file():
        raise SystemExit(f"não achei {fonte}")

    info = _ffprobe(fonte)
    largura = int(info["width"])
    altura = int(info["height"])
    fps = _fps(info.get("avg_frame_rate") or "0/1")
    exigido = (int(MODO["width"]), int(MODO["height"]))
    fps_ok = abs(fps - float(MODO["fps"])) <= 5.0

    print(f"fonte: {fonte}")
    print(f"medido: {largura}x{altura} @ {fps:.2f} fps  codec={info.get('codec_name')}")
    print(f"exigido: {exigido[0]}x{exigido[1]} @ {MODO['fps']} {MODO['codec']}")

    if (largura, altura) != exigido:
        print(
            "REPROVADO: resolução errada. Não copio. Não abro Caliscope. "
            "Regrave com calibracao/abrir_skellycam_s600.py",
            file=sys.stderr,
        )
        return 2
    if not fps_ok:
        print(
            f"REPROVADO: fps {fps:.2f} fora de {MODO['fps']}±5. "
            "A S600 neste modo tem de entregar ~60.",
            file=sys.stderr,
        )
        return 2

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    if fonte.resolve() != DESTINO.resolve():
        shutil.copy2(fonte, DESTINO)
    print(f"ACEITO → {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
