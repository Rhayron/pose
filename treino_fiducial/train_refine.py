"""Treino do RefineNet-UW (estágio 2, subpixel).

Uso (GPU):   python train_refine.py --data data --epochs 20 --batch 256
Smoke (CPU): python train_refine.py --data data --max-steps 120 --batch 32 --workers 0 --val-limit 64

Melhorias sobre o train.py v1 (recomendações da auditoria):
- scheduler cosine com warmup;
- métricas de validação robustas: MEDIANA do erro (px) + taxa <1 px e <2 px;
- salvamento atômico; log CSV separado (refine_log.csv).
Loss: SmoothL1 sobre o offset normalizado.
"""
import argparse
import csv
import math
import os
import time

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from refine_dataset import RefinePatchDataset, MAX_OFF
from refine_model import RefineNetUW


def atomic_save(obj, path):
    tmp = path + ".tmp"
    torch.save(obj, tmp)
    os.replace(tmp, path)


def evaluate(model, loader, device):
    model.eval()
    errs = []
    with torch.no_grad():
        for x, t in loader:
            p = model(x.to(device)).cpu()
            e = ((p - t) * MAX_OFF).norm(dim=-1)  # erro em px
            errs.extend(e.tolist())
    model.train()
    errs = np.array(errs)
    return float(np.median(errs)), float((errs < 1).mean()), float((errs < 2).mean()), len(errs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--ckpt", default="refine_ckpt.pt")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--val-limit", type=int, default=0)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device}")

    tr = RefinePatchDataset(args.data, "train", augment=True)
    va = RefinePatchDataset(args.data, "val", augment=False)
    if args.val_limit:
        va.items = va.items[:: max(1, len(va.items) // args.val_limit)]
    print(f"train={len(tr)} val={len(va)} (patches de canto)")
    ltr = DataLoader(tr, batch_size=args.batch, shuffle=True, num_workers=args.workers, drop_last=True)
    lva = DataLoader(va, batch_size=args.batch, num_workers=args.workers)

    model = RefineNetUW().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    scaler = torch.amp.GradScaler(enabled=device == "cuda")
    crit = nn.SmoothL1Loss(beta=0.1)

    total_steps = args.max_steps or args.epochs * (len(tr) // args.batch)

    def lr_at(s):
        if s < args.warmup:
            return args.lr * s / max(args.warmup, 1)
        p = (s - args.warmup) / max(total_steps - args.warmup, 1)
        return args.lr * 0.5 * (1 + math.cos(math.pi * min(p, 1.0)))

    step, best = 0, float("inf")
    if os.path.exists(args.ckpt):
        st = torch.load(args.ckpt, map_location=device)
        model.load_state_dict(st["model"])
        opt.load_state_dict(st["opt"])
        step, best = st["step"], st["best"]
        print(f"retomado do passo {step}")

    logf = open("refine_log.csv", "a", newline="")
    log = csv.writer(logf)
    if step == 0:
        log.writerow(["step", "loss", "lr", "val_mediana_px", "val_sub1px", "val_sub2px", "s_por_step"])

    t0 = time.time()
    done = False
    for ep in range(args.epochs):
        if done:
            break
        for x, t in ltr:
            for g in opt.param_groups:
                g["lr"] = lr_at(step)
            x, t = x.to(device), t.to(device)
            with torch.amp.autocast(device_type=device, enabled=device == "cuda"):
                loss = crit(model(x), t)
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            step += 1
            if step % 25 == 0:
                dt = (time.time() - t0) / 25
                t0 = time.time()
                print(f"step {step} loss {loss.item():.5f} lr {lr_at(step):.2e} ({dt:.2f}s/step)", flush=True)
                log.writerow([step, f"{loss.item():.6f}", f"{lr_at(step):.2e}", "", "", "", f"{dt:.2f}"])
                logf.flush()
            if args.max_steps and step >= args.max_steps:
                done = True
                break
        med, s1, s2, n = evaluate(model, lva, device)
        print(f"[val] epoca {ep} mediana={med:.2f}px  <1px={s1:.1%}  <2px={s2:.1%} (n={n})", flush=True)
        log.writerow([step, "", "", f"{med:.3f}", f"{s1:.4f}", f"{s2:.4f}", ""])
        logf.flush()
        atomic_save(dict(model=model.state_dict(), opt=opt.state_dict(), step=step, best=best), args.ckpt)
        if med < best:
            best = med
            atomic_save(dict(model=model.state_dict(), step=step, mediana_px=med), "refine_best.pt")

    med, s1, s2, n = evaluate(model, lva, device)
    print(f"[final] mediana={med:.2f}px  <1px={s1:.1%}  <2px={s2:.1%} (n={n})")
    atomic_save(dict(model=model.state_dict(), opt=opt.state_dict(), step=step, best=best), args.ckpt)


if __name__ == "__main__":
    main()
