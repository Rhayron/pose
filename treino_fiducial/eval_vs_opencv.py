"""Avaliação honesta: rede vs detector OpenCV clássico sob degradação controlada.

Protocolo: pega crops LIMPOS do conjunto de teste (vídeos nunca vistos no
treino), aplica níveis crescentes de degradação sintética idêntica para ambos,
e mede taxa de detecção + erro de canto contra a pseudo-label do frame limpo.

Uso: python eval_vs_opencv.py --data data --weights best.pt
"""
import argparse
import json
import os

import cv2
import numpy as np
import torch

from dataset import CornerDataset, degrade, RES
from model import CornerNetUW, corner_argmax


def opencv_detect(img):
    det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_7X7_1000))
    c, ids, _ = det.detectMarkers(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    if ids is not None and 0 in ids:
        k = list(ids.ravel()).index(0)
        return c[k].reshape(4, 2)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--weights", default="best.pt")
    ap.add_argument("--n", type=int, default=200)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = CornerNetUW().to(device).eval()
    model.load_state_dict(torch.load(args.weights, map_location=device)["model"])

    ds = CornerDataset(args.data, "test", augment=False)
    items = [r for r in ds.items if r["corners"] and r["dict"] == "7X7"][: args.n]
    print(f"amostras de teste: {len(items)}")

    levels = {"limpo": 0, "leve": 1, "medio": 2, "severo": 3}
    print(f"{'nivel':8} {'cv_taxa':>8} {'cv_err':>7} {'net_taxa':>9} {'net_err':>8}")
    for lname, lv in levels.items():
        cv_hit = net_hit = 0
        cv_err, net_err = [], []
        rng = np.random.default_rng(123)
        for r in items:
            img = cv2.imread(os.path.join(args.data, "crops", r["file"]))
            gt = np.array(r["corners"], np.float32)
            d = img.copy()
            for _ in range(lv):
                d = degrade(d, rng)
            # OpenCV
            c = opencv_detect(d)
            if c is not None:
                cv_hit += 1
                cv_err.append(float(np.linalg.norm(c - gt, axis=1).mean()))
            # rede
            s = RES / d.shape[0]
            x = cv2.resize(d, (RES, RES)).transpose(2, 0, 1)[None].astype(np.float32) / 255
            with torch.no_grad():
                hm = torch.sigmoid(model(torch.from_numpy(x).to(device)))
            pc, conf = corner_argmax(hm.cpu())
            if float(conf.min()) > 0.3:
                net_hit += 1
                net_err.append(float(np.linalg.norm(pc[0].numpy() / s - gt, axis=1).mean()))
        n = len(items)
        f = lambda v: f"{np.mean(v):.2f}" if v else "  -"
        print(f"{lname:8} {cv_hit/n:8.1%} {f(cv_err):>7} {net_hit/n:9.1%} {f(net_err):>8}")


if __name__ == "__main__":
    main()
