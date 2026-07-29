"""Seleção geométrica de picos (v3) — rejeição de outliers sem retreino.

Problema (AUDITORIA_V2): 3–9% dos cantos do estágio 1 são catastróficos (~90 px,
pico errado em reflexo/outro canto), inflando a média e quebrando o PnP.

Solução: em vez do argmax por canal, extrair top-K candidatos por canal (NMS) e
escolher a combinação que (a) forma um quadrilátero convexo plausível e
(b) DECODIFICA como o marcador ArUco 7×7 ID 0 — o padrão de bits conhecido é o
validador mais forte disponível. Combinações inválidas são descartadas; se nenhuma
validar, o quadro é rejeitado (sem detecção — melhor que canto a 90 px).

Régua pré-fixada para aprovar a v3 (fixada ANTES da avaliação, em 14/07/2026):
  - taxa de cantos >5 px cai para ≤ 2% nos níveis medio e severo;
  - mediana ≤ 1,2× a do argmax por nível;
  - perda de taxa de detecção ≤ 10 p.p. por nível (rejeição é preferível a outlier).
"""
import cv2
import numpy as np

_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_7X7_1000)
_REF = _DICT.generateImageMarker(0, 90)  # 9x9 celulas de 10 px (7x7 bits + borda)
_REFS = [np.rot90(_REF, r).copy() for r in range(4)]
_DST = np.array([[0, 0], [89, 0], [89, 89], [0, 89]], np.float32)


def topk_peaks(ch, k=3, thresh=0.15, nms=7):
    """ch: (H,W) heatmap [0,1]. Retorna lista [(x, y, conf)] em ordem de conf."""
    h = ch.copy()
    out = []
    for _ in range(k):
        idx = int(h.argmax())
        y, x = divmod(idx, h.shape[1])
        c = float(h[y, x])
        if c < thresh:
            break
        out.append((float(x), float(y), c))
        y0, y1 = max(0, y - nms), min(h.shape[0], y + nms + 1)
        x0, x1 = max(0, x - nms), min(h.shape[1], x + nms + 1)
        h[y0:y1, x0:x1] = 0
    return out


def _plausible(q):
    """q: (4,2). Convexo, sem lados degenerados, razao de lados limitada."""
    v = np.roll(q, -1, 0) - q
    cross = np.cross(v, np.roll(v, -1, 0))
    if not (np.all(cross > 0) or np.all(cross < 0)):
        return False
    L = np.linalg.norm(v, axis=1)
    if L.min() < 8 or L.max() / max(L.min(), 1e-6) > 4:
        return False
    return True


def bit_score(gray, quad):
    """Decodifica a regiao do quadrilatero e compara com o marcador ID 0 (4 rotacoes)."""
    M = cv2.getPerspectiveTransform(quad.astype(np.float32), _DST)
    w = cv2.warpPerspective(gray, M, (90, 90))
    _, wb = cv2.threshold(w, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cells = wb.reshape(9, 10, 9, 10).mean(axis=(1, 3)) > 127
    best = 0.0
    for ref in _REFS:
        rc = ref.reshape(9, 10, 9, 10).mean(axis=(1, 3)) > 127
        best = max(best, float((cells == rc).mean()))
    return best


def select_corners(hm, gray, scale, k=3, accept=0.85):
    """hm: (4,H,W) heatmaps; gray: imagem original em tons de cinza;
    scale: fator heatmap->imagem. Retorna (corners (4,2) na escala da imagem,
    score) ou (None, melhor_score)."""
    cands = [topk_peaks(hm[j], k=k) for j in range(4)]
    if any(len(c) == 0 for c in cands):
        return None, 0.0
    best_q, best_s = None, 0.0
    for i0 in range(len(cands[0])):
        for i1 in range(len(cands[1])):
            for i2 in range(len(cands[2])):
                for i3 in range(len(cands[3])):
                    q = np.array([cands[0][i0][:2], cands[1][i1][:2],
                                  cands[2][i2][:2], cands[3][i3][:2]], np.float32) / scale
                    if not _plausible(q):
                        continue
                    s = bit_score(gray, q)
                    if s > best_s:
                        best_s, best_q = s, q
    if best_q is not None and best_s >= accept:
        return best_q, best_s
    return None, best_s
