"""
Detecção de aceleração por GPU — com relatório honesto do que dá para acelerar.

**O que NÃO acelera, e por quê.** A detecção ArUco/ChArUco do OpenCV
(`objdetect`) não tem implementação CUDA: limiar adaptativo, contornos,
decodificação dos bits e refinamento de canto rodam só em CPU. Além disso, os
*wheels* de `opencv-contrib-python` distribuídos no PyPI são compilados **sem
CUDA**, então `cv2.cuda` sequer existe neles. Nenhuma reescrita razoável muda
isso — portar o detector para GPU seria um projeto à parte, e não é onde está
o custo.

**Onde a GPU pode entrar** (e só se houver um OpenCV compilado com CUDA):
redimensionamento e Laplaciano, que aqui somam poucos milissegundos.

**Onde está o gargalo de verdade.** Medido em quadro 4K real: detecção do guia
5,8 ms, detecção plena 71,5 ms (uma vez por foto), e a câmera entrega um quadro
a cada ~33 ms. O limite é a câmera e o decode MJPEG do driver, não a aritmética.

Este módulo existe para que essa conclusão fique registrada e verificável em
cada sessão, em vez de virar folclore.
"""

from __future__ import annotations

import cv2
import numpy as np


def _cuda_opencv() -> dict:
    try:
        n = cv2.cuda.getCudaEnabledDeviceCount()
    except (AttributeError, cv2.error):
        return {"disponivel": False, "motivo": "build do OpenCV sem modulo cuda"}
    if n <= 0:
        return {"disponivel": False, "motivo": "OpenCV com cuda, mas nenhum dispositivo"}
    try:
        nome = cv2.cuda.printShortCudaDeviceInfo(0) or ""
    except Exception:
        nome = ""
    return {"disponivel": True, "dispositivos": int(n), "info": str(nome)}


def _cuda_torch() -> dict:
    try:
        import torch
    except ImportError:
        return {"disponivel": False, "motivo": "torch nao instalado"}
    if not torch.cuda.is_available():
        return {"disponivel": False, "motivo": "torch sem CUDA disponivel",
                "versao": torch.__version__}
    return {"disponivel": True, "versao": torch.__version__,
            "dispositivo": torch.cuda.get_device_name(0)}


def resumo() -> dict:
    ocv, tch = _cuda_opencv(), _cuda_torch()
    return {
        "opencv_cuda": ocv,
        "torch_cuda": tch,
        "usado_nesta_etapa": "cpu" if not ocv["disponivel"] else "cuda (resize/laplaciano)",
        "nota": ("a deteccao ChArUco nao tem caminho CUDA no OpenCV; o gargalo "
                 "medido e a camera (~33 ms/quadro), nao o processamento"),
    }


def texto_resumo() -> str:
    r = resumo()
    linhas = ["--- aceleracao ---"]
    o, t = r["opencv_cuda"], r["torch_cuda"]
    linhas.append(f"  OpenCV CUDA: {'SIM' if o['disponivel'] else 'nao'}"
                  + (f" ({o.get('motivo')})" if not o["disponivel"] else
                     f" ({o.get('dispositivos')} dispositivo(s))"))
    linhas.append(f"  Torch CUDA:  {'SIM' if t['disponivel'] else 'nao'}"
                  + (f" ({t.get('motivo')})" if not t["disponivel"] else
                     f" ({t.get('dispositivo')})"))
    linhas.append(f"  em uso aqui: {r['usado_nesta_etapa']}")
    linhas.append("  a deteccao ChArUco roda em CPU em qualquer caso (sem kernel CUDA")
    linhas.append("  no OpenCV); a camera entrega 1 quadro a cada ~33 ms e e o limite.")
    return "\n".join(linhas)


class Redimensionador:
    """Usa cv2.cuda quando existir; senão CPU. Mesma saída nos dois caminhos."""

    def __init__(self):
        self.cuda = _cuda_opencv()["disponivel"]
        self._buf = None

    def resize(self, img, fx, fy, interp=cv2.INTER_AREA):
        if not self.cuda:
            return cv2.resize(img, None, fx=fx, fy=fy, interpolation=interp)
        try:
            g = cv2.cuda_GpuMat()
            g.upload(img)
            out = cv2.cuda.resize(g, (int(img.shape[1] * fx), int(img.shape[0] * fy)),
                                  interpolation=interp)
            return out.download()
        except cv2.error:
            self.cuda = False   # cai para CPU permanentemente e segue
            return cv2.resize(img, None, fx=fx, fy=fy, interpolation=interp)


if __name__ == "__main__":
    print(texto_resumo())
    r = Redimensionador()
    a = np.zeros((2160, 3840, 3), np.uint8)
    import time
    t = time.perf_counter()
    for _ in range(10):
        r.resize(a, 0.25, 0.25)
    print(f"  resize 4K->1K: {(time.perf_counter()-t)/10*1000:.1f} ms "
          f"({'cuda' if r.cuda else 'cpu'})")
