"""Dataset PyTorch com augmentations de degradação subaquática.

Estratégia (estilo DeepArUco): as pseudo-labels vêm de frames onde o detector
clássico funciona (água limpa). O modelo aprende a ser robusto via degradação
sintética agressiva aplicada em treino — escuridão, blur, véu de espalhamento,
ruído — condições onde o clássico falha. Assim o aluno pode superar o professor.

Partição POR VÍDEO (anti-vazamento):
  test  = 164606 (baixa nitidez) + 170626 (última/escura)
  val   = 165049
  train = demais 10 vídeos
"""
import json
import os
import random

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

TEST_VIDEOS = {"20260527_164606.mp4", "20260527_170626.mp4"}
VAL_VIDEOS = {"20260527_165049.mp4"}

RES = 256  # resolução de entrada da rede
SIGMA = 2.0  # desvio da gaussiana dos heatmaps


def gaussian_heatmaps(corners, res, sigma=SIGMA):
    """corners: (4,2) em pixels da imagem res x res -> (4,res,res)."""
    hm = np.zeros((4, res, res), np.float32)
    if corners is None:
        return hm
    yy, xx = np.mgrid[0:res, 0:res]
    for j, (x, y) in enumerate(corners):
        if 0 <= x < res and 0 <= y < res:
            hm[j] = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))
    return hm


def degrade(img, rng):
    """Degradação subaquática sintética. img: BGR uint8."""
    img = img.astype(np.float32) / 255.0
    # escuridão (gamma + ganho)
    if rng.random() < 0.7:
        img = img ** rng.uniform(1.0, 3.5) * rng.uniform(0.25, 1.0)
    # dominante cromática (perda de vermelho)
    if rng.random() < 0.5:
        img[..., 2] *= rng.uniform(0.4, 1.0)
        img[..., 1] *= rng.uniform(0.8, 1.0)
    # véu de espalhamento (backscatter): mistura com cinza-esverdeado
    if rng.random() < 0.6:
        veil = np.array([rng.uniform(0.3, 0.6), rng.uniform(0.4, 0.7), rng.uniform(0.3, 0.5)], np.float32)
        a = rng.uniform(0.1, 0.55)
        img = (1 - a) * img + a * veil
    # blur gaussiano ou de movimento
    r = rng.random()
    if r < 0.4:
        k = rng.choice([3, 5, 7])
        img = cv2.GaussianBlur(img, (k, k), 0)
    elif r < 0.7:
        k = rng.choice([5, 7, 9, 11])
        kern = np.zeros((k, k), np.float32)
        ang = rng.uniform(0, np.pi)
        cv2.line(kern, (0, k // 2), (k - 1, k // 2), 1.0, 1)
        M = cv2.getRotationMatrix2D((k / 2 - 0.5, k / 2 - 0.5), np.degrees(ang), 1)
        kern = cv2.warpAffine(kern, M, (k, k))
        img = cv2.filter2D(img, -1, kern / max(kern.sum(), 1e-6))
    # ruído
    if rng.random() < 0.6:
        img = img + rng.normal(0, rng.uniform(0.01, 0.06), img.shape).astype(np.float32)
    return np.clip(img * 255, 0, 255).astype(np.uint8)


class CornerDataset(Dataset):
    def __init__(self, root, split="train", augment=True, res=RES):
        self.root = root
        self.res = res
        self.augment = augment
        self.items = []
        for line in open(os.path.join(root, "index.jsonl")):
            r = json.loads(line)
            v = r["video"]
            part = "test" if v in TEST_VIDEOS else "val" if v in VAL_VIDEOS else "train"
            if part == split:
                self.items.append(r)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        r = self.items[idx]
        img = cv2.imread(os.path.join(self.root, "crops", r["file"]))
        corners = np.array(r["corners"], np.float32) if r["corners"] else None
        rng = np.random.default_rng()

        # jitter geométrico (shift/escala) via crop interno + resize p/ RES
        s = self.res / img.shape[0]
        if self.augment:
            img = degrade(img, rng)
            if rng.random() < 0.5:  # flip horizontal preserva o conjunto de 4 cantos
                img = img[:, ::-1].copy()
                if corners is not None:
                    corners = corners.copy()
                    corners[:, 0] = img.shape[1] - 1 - corners[:, 0]
                    corners = corners[[1, 0, 3, 2]]  # mantém ordem consistente
        img = cv2.resize(img, (self.res, self.res))
        if corners is not None:
            corners = corners * s

        hm = gaussian_heatmaps(corners, self.res)
        x = torch.from_numpy(img.transpose(2, 0, 1)).float() / 255.0
        return x, torch.from_numpy(hm), torch.tensor(0 if corners is None else 1)
