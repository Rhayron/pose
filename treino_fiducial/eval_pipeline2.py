"""Avaliação do pipeline de 2 estágios: CornerNet (grosso) + RefineNet (subpixel).

MESMO protocolo, itens e semente do eval_vs_opencv.py — as linhas 'cv' e 'grosso'
devem reproduzir a tabela v1, isolando o ganho do refinador (única variável nova).

Por nível de degradação reporta:
  cv_taxa/cv_err       — OpenCV clássico
  g_taxa/g_med         — estágio 1 sozinho (taxa; MEDIANA do erro, px do crop 384)
  r_med/r_sub2px       — estágio 1+2 (mediana refinada; fração de cantos <2 px)

Uso: python eval_pipeline2.py --data data --coarse best.pt --refine refine_best.pt
"""
import argparse
import json
import os

import cv2
import numpy as np
import torch

from dataset import CornerDataset, degrade, RES
from model import CornerNetUW, corner_argmax
from refine_dataset import PATCH, MAX_OFF
from refine_model import RefineNetUW
from eval_vs_opencv import opencv_detect


def refine_corners(refiner, img, coarse, device):
    """coarse: (4,2) px na escala do crop original. Retorna (4,2) refinado."""
    H, W = img.shape[:2]
    patches, origins = [], []
    for cx, cy in coarse:
        px = float(np.clip(cx - PATCH / 2, 0, W - PATCH))
        py = float(np.clip(cy - PATCH / 2, 0, H - PATCH))
        M = np.float32([[1, 0, -px], [0, 1, -py]])
        patches.append(cv2.warpAffine(img, M, (PATCH, PATCH)))
        origins.append((px, py))
    x = torch.from_numpy(np.stack(patches).transpose(0, 3, 1, 2)).float().to(device) / 255.0
    with torch.no_grad():
        off = refiner(x).cpu().numpy() * MAX_OFF
    out = np.array([[ox + PATCH / 2 + o[0], oy + PATCH / 2 + o[1]] for (ox, oy), o in zip(origins, off)], np.float32)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--coarse", default="best.pt")
    ap.add_argument("--refine", default="refine_best.pt")
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    coarse_net = CornerNetUW().to(device).eval()
    coarse_net.load_state_dict(torch.load(args.coarse, map_location=device)["model"])
    refiner = RefineNetUW().to(device).eval()
    refiner.load_state_dict(torch.load(args.refine, map_location=device)["model"])

    ds = CornerDataset(args.data, "test", augment=False)
    items = [r for r in ds.items if r["corners"] and r["dict"] == "7X7"][: args.n]
    print(f"amostras de teste: {len(items)}")

    levels = {"limpo": 0, "leve": 1, "medio": 2, "severo": 3}
    print(f"{'nivel':8} {'cv_taxa':>8} {'cv_err':>7} {'g_taxa':>8} {'g_med':>7} {'r_med':>7} {'r_sub2px':>9}")
    for lname, lv in levels.items():
        cv_hit = g_hit = 0
        cv_err, g_err, r_err = [], [], []
        r_sub2 = t_corners = 0
        rng = np.random.default_rng(123)
        for r in items:
            img = cv2.imread(os.path.join(args.data, "crops", r["file"]))
            gt = np.array(r["corners"], np.float32)
            d = img.copy()
            for _ in range(lv):
                d = degrade(d, rng)
            c = opencv_detect(d)
            if c is not None:
                cv_hit += 1
                cv_err.append(float(np.linalg.norm(c - gt, axis=1).mean()))
            s = RES / d.shape[0]
            x = cv2.resize(d, (RES, RES)).transpose(2, 0, 1)[None].astype(np.float32) / 255
            with torch.no_grad():
                hm = torch.sigmoid(coarse_net(torch.from_numpy(x).to(device)))
            pc, conf = corner_argmax(hm.cpu())
            if float(conf.min()) > 0.3:
                g_hit += 1
                coarse = pc[0].numpy() / s  # escala do crop 384
                g_err.append(float(np.median(np.linalg.norm(coarse - gt, axis=1))))
                ref = refine_corners(refiner, d, coarse, device)
                e = np.linalg.norm(ref - gt, axis=1)
                r_err.append(float(np.median(e)))
                r_sub2 += int((e < 2).sum())
                t_corners += 4
        n = len(items)
        f = lambda v: f"{np.median(v):.2f}" if v else "  -"
        fm = lambda v: f"{np.mean(v):.2f}" if v else "  -"
        print(f"{lname:8} {cv_hit/n:8.1%} {fm(cv_err):>7} {g_hit/n:8.1%} {f(g_err):>7} {f(r_err):>7} {r_sub2/max(t_corners,1):9.1%}")


if __name__ == "__main__":
    main()
