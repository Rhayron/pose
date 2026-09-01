"""Grava S600 4K no disco e abre preview 1280x720.

ffmpeg copia MJPEG para o arquivo (RAM plana) e manda um stream
escalado via UDP para o ffplay. q no terminal do ffmpeg para.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MODO = json.loads((RAIZ / "modo_s600.json").read_text(encoding="utf-8"))["mode"]
SAIDA = RAIZ / "caliscope-workspace" / "calibration" / "intrinsic" / "cam_1.mp4"
UDP = "udp://127.0.0.1:2345?pkt_size=1316"


def main() -> int:
    w, h, fps = int(MODO["width"]), int(MODO["height"]), int(MODO["fps"])
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"Gravando {w}x{h}@{fps} MJPEG → {SAIDA}\n"
        "Preview 1280x720 numa janela à parte.\n"
        "q no terminal = parar.",
        flush=True,
    )

    ffmpeg = [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "dshow",
        "-video_size", f"{w}x{h}",
        "-framerate", str(fps),
        "-vcodec", "mjpeg",
        "-i", "video=EMEET SmartCam S600",
        "-map", "0:v", "-c:v", "copy", "-an", str(SAIDA),
        "-map", "0:v", "-an",
        "-vf", "scale=1280:720",
        "-pix_fmt", "yuv420p",
        "-f", "mpegts", UDP,
    ]
    ffplay = [
        "ffplay", "-hide_banner", "-loglevel", "error",
        "-fflags", "nobuffer", "-flags", "low_delay", "-framedrop",
        "-alwaysontop",
        "-window_title", f"S600 preview (grava {w}x{h}@{fps})",
        "-x", "1280", "-y", "720",
        UDP.split("?", 1)[0],
    ]

    rec = subprocess.Popen(ffmpeg)
    time.sleep(1.2)
    prev = subprocess.Popen(ffplay)
    code = rec.wait()
    prev.terminate()
    try:
        prev.wait(timeout=3)
    except subprocess.TimeoutExpired:
        prev.kill()
    print(f"ffmpeg saiu com {code}. Arquivo: {SAIDA} existe={SAIDA.exists()}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
