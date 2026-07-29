"""Extrai crops de treino a partir dos vídeos + labels JSONL.

Cada crop: 384x384 BGR centrado no marcador (com jitter), corners salvos em
coordenadas do crop. Negativos (sem marcador) são extraídos de regiões afastadas.

Uso: python make_crops.py --videos ../videos --labels data/labels_all.jsonl --out data/crops [--start 0 --end 13]
"""
import argparse, json, os, random
from collections import defaultdict

import cv2
import numpy as np

CROP = 384
random.seed(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", default="../videos")
    ap.add_argument("--labels", default="data/labels_all.jsonl")
    ap.add_argument("--out", default="data/crops")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=99)
    ap.add_argument("--neg-frac", type=float, default=0.2)
    args = ap.parse_args()

    by_video = defaultdict(dict)  # video -> frame_idx -> markers
    for line in open(args.labels):
        r = json.loads(line)
        # filtra falsos positivos: só ids vistos com frequência
        ms = [m for m in r["markers"] if (m["dict"], m["id"]) in {("7X7", 0), ("5X5", 3)}]
        if ms:
            by_video[r["video"]][r["frame"]] = ms

    os.makedirs(args.out, exist_ok=True)
    index = []
    for vi, (video, frames) in enumerate(sorted(by_video.items())):
        if not (args.start <= vi < args.end):
            continue
        cap = cv2.VideoCapture(os.path.join(args.videos, video))
        i = 0
        n_pos = n_neg = 0
        while True:
            if not cap.grab():
                break
            if i in frames:
                ok, fr = cap.retrieve()
                if not ok:
                    break
                H, W = fr.shape[:2]
                for k, m in enumerate(frames[i]):
                    c = np.array(m["corners"], np.float32)
                    cx, cy = c.mean(0)
                    jx, jy = random.randint(-60, 60), random.randint(-60, 60)
                    x0 = int(np.clip(cx + jx - CROP / 2, 0, W - CROP))
                    y0 = int(np.clip(cy + jy - CROP / 2, 0, H - CROP))
                    crop = fr[y0 : y0 + CROP, x0 : x0 + CROP]
                    cc = c - [x0, y0]
                    if cc.min() < 4 or cc.max() > CROP - 4:
                        continue
                    name = f"{video[:-4]}_{i:05d}_{k}.jpg"
                    cv2.imwrite(os.path.join(args.out, name), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
                    index.append(dict(file=name, video=video, frame=i, dict=m["dict"], id=m["id"], corners=cc.tolist()))
                    n_pos += 1
                # negativo ocasional: longe do marcador
                if random.random() < args.neg_frac:
                    c = np.array(frames[i][0]["corners"], np.float32)
                    for _ in range(10):
                        x0 = random.randint(0, W - CROP)
                        y0 = random.randint(0, H - CROP)
                        if abs(x0 + CROP / 2 - c.mean(0)[0]) > CROP or abs(y0 + CROP / 2 - c.mean(0)[1]) > CROP:
                            name = f"{video[:-4]}_{i:05d}_neg.jpg"
                            cv2.imwrite(os.path.join(args.out, name), fr[y0 : y0 + CROP, x0 : x0 + CROP], [cv2.IMWRITE_JPEG_QUALITY, 92])
                            index.append(dict(file=name, video=video, frame=i, dict=None, id=None, corners=None))
                            n_neg += 1
                            break
            i += 1
        cap.release()
        print(video, "pos:", n_pos, "neg:", n_neg, flush=True)

    mode = "a" if args.start > 0 else "w"
    with open(os.path.join(args.out, "..", "index.jsonl"), mode) as f:
        for r in index:
            f.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    main()
