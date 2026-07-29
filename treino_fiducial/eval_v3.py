"""Avaliação v3: argmax (baseline) vs seleção geométrica de picos, mesmo protocolo.

Uso: python eval_v3.py <nivel> [--n 60]   (nivel: limpo|leve|medio|severo)
Compara por canto: mediana, P90, taxa >5 px; e taxa de detecção de cada método.
Universo: todos os frames de teste (a v3 tem critério próprio de aceitação: decode).
"""
import argparse
import os

import cv2
import numpy as np
import torch

from dataset import CornerDataset, degrade, RES
from model import CornerNetUW, corner_argmax
from peak_select import select_corners


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nivel", choices=["limpo", "leve", "medio", "severo"])
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--coarse", default="best_v1_step3220.pt")
    ap.add_argument("--data", default="data")
    args = ap.parse_args()
    lv = dict(limpo=0, leve=1, medio=2, severo=3)[args.nivel]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    net = CornerNetUW().to(device).eval()
    net.load_state_dict(torch.load(args.coarse, map_location=device)["model"])

    ds = CornerDataset(args.data, "test", augment=False)
    items = [r for r in ds.items if r["corners"] and r["dict"] == "7X7"][: args.n]

    am_err, v3_err = [], []
    am_det = v3_det = 0
    rng = np.random.default_rng(123)
    for r in items:
        img = cv2.imread(os.path.join(args.data, "crops", r["file"]))
        gt = np.array(r["corners"], np.float32)
        d = img.copy()
        for _ in range(lv):
            d = degrade(d, rng)
        s = RES / d.shape[0]
        x = cv2.resize(d, (RES, RES)).transpose(2, 0, 1)[None].astype(np.float32) / 255
        with torch.no_grad():
            hm = torch.sigmoid(net(torch.from_numpy(x).to(device)))[0].cpu().numpy()
        # baseline argmax (gate conf>0.3, como v1)
        pc, conf = corner_argmax(torch.from_numpy(hm)[None])
        if float(conf.min()) > 0.3:
            am_det += 1
            am_err.extend(np.linalg.norm(pc[0].numpy() / s - gt, axis=1).tolist())
        # v3
        gray = cv2.cvtColor(d, cv2.COLOR_BGR2GRAY)
        q, score = select_corners(hm, gray, s)
        if q is not None:
            v3_det += 1
            v3_err.extend(np.linalg.norm(q - gt, axis=1).tolist())

    n = len(items)
    def rep(nome, det, errs):
        e = np.array(errs) if errs else np.array([np.nan])
        print(f"  {nome:8} det {det/n:5.1%} | med {np.median(e):5.2f} | P90 {np.percentile(e,90):6.2f} | >5px {(e>5).mean():5.1%} (cantos={len(errs)})")
    print(f"[{args.nivel}] n={n} frames")
    rep("argmax", am_det, am_err)
    rep("v3", v3_det, v3_err)


if __name__ == "__main__":
    main()
