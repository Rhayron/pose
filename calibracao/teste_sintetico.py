"""
Teste do INSTRUMENTO antes da medida: o pipeline recupera intrínsecos conhecidos?

Renderiza vistas sintéticas do tabuleiro com uma câmera de referência (K e
distorção arbitrados por nós), roda `calibrar.py` exatamente como no uso real
e verifica se os parâmetros recuperados batem com os de referência.

Se este teste falhar, qualquer número medido na webcam é suspeito — e o
problema estará no código, não na lente. É o análogo dos "testes de geometria
ouro" previstos no WP0 do plano de implementação.

Uso:
    python teste_sintetico.py
    python teste_sintetico.py --n-vistas 40 --ruido 2.0
"""

from __future__ import annotations

import argparse
import json

import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from nucleo import ConfigTabuleiro, agora, construir_board

# --- câmera de referência (a "verdade" deste teste) -----------------------
GT_RES = (1280, 720)
GT_K = np.array([[905.0, 0.0, 646.0],
                 [0.0, 902.0, 351.0],
                 [0.0, 0.0, 1.0]], np.float64)
GT_DIST = np.array([[-0.185, 0.042, 0.0012, -0.0008, 0.0]], np.float64)
GT_QUADRADO_MM = 35.0

# Tolerâncias do teste — fixadas antes da execução.
TOL = {
    "fx_rel": 0.01,        # 1%
    "fy_rel": 0.01,
    "c_px_frac": 0.01,     # 1% da dimensão da imagem
    "k1_rel": 0.15,
    "rms_px": 0.5,
}


def gerar_poses(n, rng, largura_mm, altura_mm):
    """Poses que cobrem quadro, escala e inclinação — como manda o protocolo."""
    centro = np.array([largura_mm / 2, altura_mm / 2, 0.0])
    alvos = [(0.25, 0.25), (0.5, 0.25), (0.75, 0.25),
             (0.25, 0.5), (0.5, 0.5), (0.75, 0.5),
             (0.25, 0.75), (0.5, 0.75), (0.75, 0.75)]
    Kinv = np.linalg.inv(GT_K)
    poses = []
    for i in range(n):
        fx_alvo, fy_alvo = alvos[i % len(alvos)]
        u0 = fx_alvo * GT_RES[0] + rng.normal(0, 20)
        v0 = fy_alvo * GT_RES[1] + rng.normal(0, 20)
        # distâncias em três faixas -> cobre os bins de escala pequeno/médio/grande
        faixa = [(195.0, 250.0), (330.0, 500.0), (600.0, 950.0)][i % 3]
        z0 = rng.uniform(*faixa)
        # inclinação: 1/3 quase frontal, 2/3 inclinadas em direções variadas
        amp = 8.0 if i % 3 == 0 else rng.uniform(20.0, 45.0)
        ang = rng.uniform(0, 2 * np.pi)
        rvec = np.array([amp * np.cos(ang), amp * np.sin(ang),
                         rng.uniform(-25, 25)]) * np.pi / 180.0
        R, _ = cv2.Rodrigues(rvec)
        raio = Kinv @ np.array([u0, v0, 1.0])
        t = raio * (z0 / raio[2]) - R @ centro
        poses.append((R, t))
    return poses


def renderizar(textura, ppmm, R, t, raios, ruido, rng):
    """Projeção inversa exata de um plano texturizado, com distorção da GT."""
    n = R[:, 2]                      # normal do plano do tabuleiro, em coords. da câmera
    denom = raios @ n
    s = float(n @ t) / np.where(np.abs(denom) < 1e-9, np.nan, denom)
    P = raios * s[:, None]           # ponto 3D na câmera
    B = (P - t) @ R                  # = R^T (P - t) -> coords. do tabuleiro (mm)
    valido = np.isfinite(s) & (s > 0)
    mapx = np.where(valido, B[:, 0] * ppmm, -1).astype(np.float32).reshape(GT_RES[1], GT_RES[0])
    mapy = np.where(valido, B[:, 1] * ppmm, -1).astype(np.float32).reshape(GT_RES[1], GT_RES[0])
    img = cv2.remap(textura, mapx, mapy, cv2.INTER_AREA,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=235)
    if ruido > 0:
        img = np.clip(img.astype(np.float32) + rng.normal(0, ruido, img.shape), 0, 255).astype(np.uint8)
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-vistas", type=int, default=36)
    ap.add_argument("--ruido", type=float, default=1.5, help="sigma do ruído gaussiano (níveis)")
    ap.add_argument("--saida", default="saida_teste")
    ap.add_argument("--semente", type=int, default=123)
    ap.add_argument("--manter", action="store_true", help="não apagar as imagens ao final")
    args = ap.parse_args()

    rng = np.random.default_rng(args.semente)
    raiz = Path(args.saida)
    imagens = raiz / "imagens"
    imagens.mkdir(parents=True, exist_ok=True)
    # limpa vistas de execuções anteriores (sem rmtree: em pastas montadas do
    # Windows a remoção de diretório pode ser negada e mascarar o resultado)
    restantes = []
    for p in imagens.glob("*.png"):
        try:
            p.unlink()
        except OSError:
            restantes.append(p.name)
    if restantes:
        raise SystemExit(f"[erro] não consegui limpar {len(restantes)} imagens antigas em "
                         f"{imagens} — apague a pasta manualmente antes de repetir o teste")

    cfg = ConfigTabuleiro(square_mm_nominal=GT_QUADRADO_MM,
                          marker_mm_nominal=round(0.75 * GT_QUADRADO_MM, 1),
                          square_mm_medido=GT_QUADRADO_MM,  # no sintético a escala é exata
                          gerado_em=agora(), opencv=cv2.__version__)
    cfg_path = raiz / "tabuleiro.json"
    cfg.salvar(cfg_path)
    board, _ = construir_board(cfg, GT_QUADRADO_MM, cfg.marker_mm_nominal)

    largura_mm = cfg.squares_x * GT_QUADRADO_MM
    altura_mm = cfg.squares_y * GT_QUADRADO_MM
    ppmm = 8.0
    textura = board.generateImage((int(largura_mm * ppmm), int(altura_mm * ppmm)),
                                  marginSize=0, borderBits=1)

    # rays: pixel -> direção normalizada. Depende só de K/dist -> calcula uma vez.
    u, v = np.meshgrid(np.arange(GT_RES[0], dtype=np.float32),
                       np.arange(GT_RES[1], dtype=np.float32))
    pix = np.stack([u.ravel(), v.ravel()], 1).reshape(-1, 1, 2)
    norm = cv2.undistortPoints(pix, GT_K, GT_DIST).reshape(-1, 2)
    raios = np.concatenate([norm, np.ones((len(norm), 1))], 1).astype(np.float64)

    print(f"[..] renderizando {args.n_vistas} vistas {GT_RES[0]}x{GT_RES[1]}")
    n_ok = 0
    for i, (R, t) in enumerate(gerar_poses(args.n_vistas, rng, largura_mm, altura_mm), 1):
        img = renderizar(textura, ppmm, R, t, raios, args.ruido, rng)
        # descarta vistas onde o tabuleiro quase não aparece
        if (img < 128).mean() < 0.01:
            continue
        cv2.imwrite(str(imagens / f"img_{i:04d}.png"), img)
        n_ok += 1
    print(f"[ok] {n_ok} imagens em {imagens}")
    if n_ok < 12:
        raise SystemExit("[erro] geração produziu poucas vistas úteis — revise gerar_poses")

    cmd = [sys.executable, str(Path(__file__).parent / "calibrar.py"),
           "--imagens", str(imagens), "--tabuleiro", str(cfg_path),
           "--saida", str(raiz), "--nome-camera", "sintetica",
           "--particoes", "10", "--bootstrap", "80"]
    print("[..] rodando calibrar.py sobre as vistas sintéticas")
    proc = subprocess.run(cmd, cwd=str(Path(__file__).parent), capture_output=True, text=True)
    print(proc.stdout[-3000:])
    if proc.stderr.strip():
        print("--- stderr ---\n" + proc.stderr[-2000:])

    saida_json = raiz / "calibracao_sintetica.json"
    if not saida_json.exists():
        raise SystemExit("[FALHA] calibrar.py não produziu resultado")
    r = json.loads(saida_json.read_text(encoding="utf-8"))

    fx, fy, cx, cy = r["fx"], r["fy"], r["cx"], r["cy"]
    k1 = r["dist"][0]
    checks = {
        "fx": (abs(fx - GT_K[0, 0]) / GT_K[0, 0] <= TOL["fx_rel"],
               f"{fx:.2f} vs {GT_K[0,0]:.2f}  ({(fx-GT_K[0,0])/GT_K[0,0]*100:+.2f}%)"),
        "fy": (abs(fy - GT_K[1, 1]) / GT_K[1, 1] <= TOL["fy_rel"],
               f"{fy:.2f} vs {GT_K[1,1]:.2f}  ({(fy-GT_K[1,1])/GT_K[1,1]*100:+.2f}%)"),
        "cx": (abs(cx - GT_K[0, 2]) <= TOL["c_px_frac"] * GT_RES[0],
               f"{cx:.2f} vs {GT_K[0,2]:.2f}  ({cx-GT_K[0,2]:+.2f} px)"),
        "cy": (abs(cy - GT_K[1, 2]) <= TOL["c_px_frac"] * GT_RES[1],
               f"{cy:.2f} vs {GT_K[1,2]:.2f}  ({cy-GT_K[1,2]:+.2f} px)"),
        "k1": (abs(k1 - GT_DIST[0, 0]) / abs(GT_DIST[0, 0]) <= TOL["k1_rel"],
               f"{k1:.4f} vs {GT_DIST[0,0]:.4f}  ({(k1-GT_DIST[0,0])/GT_DIST[0,0]*100:+.1f}%)"),
        "rms": (r["rms_global_px"] <= TOL["rms_px"], f"{r['rms_global_px']:.4f} px"),
    }
    ic = r.get("ic95_bootstrap")
    if ic:
        lo, hi = ic["fx"]["ic95"]
        checks["fx_dentro_do_IC95"] = (lo <= GT_K[0, 0] <= hi,
                                       f"GT {GT_K[0,0]:.1f} em [{lo:.1f}, {hi:.1f}]")

    print("\n=== recuperação dos parâmetros de referência ===")
    for nome, (ok, txt) in checks.items():
        print(f"  {'OK  ' if ok else 'FALHA'} {nome:18s} {txt}")
    print(f"  ---- modelo escolhido: {r['modelo_distorcao']} "
          f"(GT gerada com k1,k2,p1,p2) | vistas usadas: {r['n_vistas']}")
    print("  ---- nota: o veredicto de COBERTURA de calibrar.py costuma reprovar aqui;\n"
          "       o amostrador sintético não otimiza cobertura. O que este teste afere\n"
          "       é a recuperação dos parâmetros, cujos critérios estão em TOL.")

    if not args.manter:
        for p in imagens.glob("*.png"):
            try:
                p.unlink()
            except OSError:
                pass

    aprovado = all(ok for ok, _ in checks.values())
    print("\n" + ("[APROVADO] o pipeline recupera a câmera de referência."
                  if aprovado else
                  "[REPROVADO] o pipeline NÃO recupera a câmera de referência — "
                  "corrigir o código antes de medir a webcam."))
    sys.exit(0 if aprovado else 1)


if __name__ == "__main__":
    main()
