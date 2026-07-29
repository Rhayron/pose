"""Dataset de patches para o refinador subpixel (estágio 2, estilo RefineNet do Deep ChArUco).

Gerado ON-THE-FLY a partir dos crops existentes (data/crops + index.jsonl) — nenhum
arquivo novo. Para cada canto rotulado: patch PATCH×PATCH cortado em posição
deslocada por um offset aleatório uniforme em [-MAX_OFF, MAX_OFF]²; o alvo é o
offset subpixel do canto em relação ao centro do patch, normalizado por MAX_OFF.

A degradação sintética é a MESMA do estágio 1 (dataset.degrade) — o refinador
precisa operar sobre a saída do detector nas mesmas condições em que ele roda.
Partição por vídeo idêntica (importa TEST_VIDEOS/VAL_VIDEOS de dataset.py).
"""
import json
import os

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

from dataset import TEST_VIDEOS, VAL_VIDEOS, degrade

PATCH = 64
MAX_OFF = 12.0  # px; simula erro de localização do estágio 1 (v1 errou ~10-25 px)


class RefinePatchDataset(Dataset):
    """Um item = um canto (4 por crop positivo)."""

    def __init__(self, root, split="train", augment=True, max_off=MAX_OFF):
        self.root = root
        self.augment = augment
        self.max_off = max_off
        self.items = []
        for line in open(os.path.join(root, "index.jsonl")):
            r = json.loads(line)
            if r["corners"] is None:
                continue
            v = r["video"]
            part = "test" if v in TEST_VIDEOS else "val" if v in VAL_VIDEOS else "train"
            if part == split:
                for j in range(4):
                    self.items.append((r["file"], r["corners"][j]))

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        fname, corner = self.items[idx]
        img = cv2.imread(os.path.join(self.root, "crops", fname))
        rng = np.random.default_rng()
        cx, cy = corner

        # offset simulando o erro do estágio 1
        if self.augment:
            off = rng.uniform(-self.max_off, self.max_off, 2)
        else:
            # validação determinística: offset fixo derivado do índice
            g = np.random.default_rng(idx)
            off = g.uniform(-self.max_off, self.max_off, 2)
        px = cx + off[0] - PATCH / 2  # canto do patch
        py = cy + off[1] - PATCH / 2
        H, W = img.shape[:2]
        px = float(np.clip(px, 0, W - PATCH))
        py = float(np.clip(py, 0, H - PATCH))

        # corte com interpolação subpixel (warpAffine) p/ não quantizar o GT
        M = np.float32([[1, 0, -px], [0, 1, -py]])
        patch = cv2.warpAffine(img, M, (PATCH, PATCH))
        if self.augment:
            patch = degrade(patch, rng)

        # alvo: posição do canto relativa ao centro do patch, normalizada
        tx = (cx - px - PATCH / 2) / self.max_off
        ty = (cy - py - PATCH / 2) / self.max_off

        x = torch.from_numpy(patch.transpose(2, 0, 1)).float() / 255.0
        return x, torch.tensor([tx, ty], dtype=torch.float32)
