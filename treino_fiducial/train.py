"""Treino do CornerNet-UW com pseudo-labels + degradação sintética.

Uso (GPU local):
    python train.py --data data --epochs 30 --batch 32
Smoke test (CPU):
    python train.py --data data --max-steps 150 --batch 8 --res 128 --workers 0 --val-limit 16

Métricas: loss MSE de heatmap; erro médio de canto (px) na validação;
taxa de acerto (<3 px). Checkpoint retomável (salvamento atômico), semente fixa, log CSV.
"""
import argparse
import csv
import os
import time

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from dataset import CornerDataset
from model import CornerNetUW, corner_argmax


def atomic_save(obj, path):
    tmp = path + ".tmp"
    torch.save(obj, tmp)
    os.replace(tmp, path)


def evaluate(model, loader, device, res):
    model.eval()
    errs, hits, n = [], 0, 0
    with torch.no_grad():
        for x, hm, has in loader:
            x = x.to(device)
            pred = torch.sigmoid(model(x)).cpu()
            pc, conf = corner_argmax(pred)
            gc, _ = corner_argmax(hm)
            for b in range(x.shape[0]):
                if has[b] == 0:
                    continue
                e = (pc[b] - gc[b]).norm(dim=-1)  # px na resolução da rede
                errs.append(e.mean().item())
                hits += int((e < 3.0).all())
                n += 1
    model.train()
    return (float(np.mean(errs)) if errs else float("nan"), hits / max(n, 1), n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--res", type=int, default=256)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-steps", type=int, default=0, help="0 = sem limite (usa epochs)")
    ap.add_argument("--ckpt", default="ckpt.pt")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--val-limit", type=int, default=0, help="limita amostras de val (smoke test)")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device}")

    tr = CornerDataset(args.data, "train", augment=True, res=args.res)
    va = CornerDataset(args.data, "val", augment=False, res=args.res)
    if args.val_limit:
        va.items = va.items[:: max(1, len(va.items) // args.val_limit)]
    print(f"train={len(tr)} val={len(va)}")
    ltr = DataLoader(tr, batch_size=args.batch, shuffle=True, num_workers=args.workers, drop_last=True)
    lva = DataLoader(va, batch_size=args.batch, num_workers=args.workers)

    model = CornerNetUW().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    scaler = torch.amp.GradScaler(enabled=device == "cuda")
    crit = nn.MSELoss()

    step, best = 0, float("inf")
    if os.path.exists(args.ckpt):
        st = torch.load(args.ckpt, map_location=device)
        model.load_state_dict(st["model"])
        opt.load_state_dict(st["opt"])
        step, best = st["step"], st["best"]
        print(f"retomado do passo {step}")

    logf = open("train_log.csv", "a", newline="")
    log = csv.writer(logf)
    if step == 0:
        log.writerow(["step", "loss", "val_err_px", "val_hit3px", "s_por_step"])

    t0 = time.time()
    done = False
    for ep in range(args.epochs):
        if done:
            break
        for x, hm, _ in ltr:
            x, hm = x.to(device), hm.to(device)
            with torch.amp.autocast(device_type=device, enabled=device == "cuda"):
                # Plano B (HANDOFF GATE 2): MSE ponderado — MSE puro colapsou p/ heatmaps nulos
                w = 1.0 + 49.0 * (hm > 0.1).float()
                loss = ((torch.sigmoid(model(x)) - hm) ** 2 * w).mean()
            opt.zero_grad()
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            step += 1
            if step % 25 == 0:
                dt = (time.time() - t0) / 25
                t0 = time.time()
                print(f"step {step} loss {loss.item():.5f} ({dt:.2f}s/step)", flush=True)
                log.writerow([step, f"{loss.item():.6f}", "", "", f"{dt:.2f}"])
                logf.flush()
            if args.max_steps and step >= args.max_steps:
                done = True
                break
        err, hit, n = evaluate(model, lva, device, args.res)
        print(f"[val] epoca {ep} erro_medio={err:.2f}px acerto<3px={hit:.1%} (n={n})", flush=True)
        log.writerow([step, "", f"{err:.3f}", f"{hit:.4f}", ""])
        logf.flush()
        atomic_save(dict(model=model.state_dict(), opt=opt.state_dict(), step=step, best=best), args.ckpt)
        if err < best:
            best = err
            atomic_save(dict(model=model.state_dict(), step=step, err=err), "best.pt")

    err, hit, n = evaluate(model, lva, device, args.res)
    print(f"[final] erro_medio={err:.2f}px acerto<3px={hit:.1%} (n={n})")
    atomic_save(dict(model=model.state_dict(), opt=opt.state_dict(), step=step, best=best), args.ckpt)


if __name__ == "__main__":
    main()
