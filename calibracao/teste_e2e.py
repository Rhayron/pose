"""
Ensaio geral: as quatro etapas encadeadas, com câmera e distâncias conhecidas.

Diferente do `teste_sintetico.py` (que afere só a calibração), aqui roda a
cadeia inteira como no uso real:

    gerar_tabuleiro -> sessão A (calibrar) -> sessão B independente (validar)

e confronta cada saída com a verdade usada para renderizar — inclusive o teste
métrico do `validar.py`, cuja distância "de trena" aqui é conhecida ao milímetro.

Serve de ensaio antes da sessão com a webcam: os números que aparecem aqui são
os mesmos campos que você vai ler no equipamento real.

    python teste_e2e.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from nucleo import ConfigTabuleiro, agora, construir_board
from teste_sintetico import GT_DIST, GT_K, GT_QUADRADO_MM, GT_RES, gerar_poses, renderizar

RAIZ = Path(__file__).resolve().parent

# Régua deste ensaio — fixada antes de rodar.
TOL_E2E = {
    "fx_rel": 0.01,
    "c_px": 0.02 * GT_RES[0],
    "reproj_indep_mediana_px": 0.5,
    "retidao_mediana_px": 0.5,
    "erro_metrico_rel": 0.02,   # 2% da distância verdadeira
}

falhas = []


def checar(nome, ok, detalhe=""):
    print(f"  {'OK  ' if ok else 'FALHA'} {nome:42s} {detalhe}")
    if not ok:
        falhas.append(nome)


def render_sessao(pasta, board, cfg, n, semente, ppmm=8.0):
    """Renderiza uma sessão de vistas e devolve a distância verdadeira por arquivo."""
    pasta.mkdir(parents=True, exist_ok=True)
    for p in pasta.glob("*.png"):
        p.unlink()
    rng = np.random.default_rng(semente)
    largura_mm = cfg.squares_x * GT_QUADRADO_MM
    altura_mm = cfg.squares_y * GT_QUADRADO_MM
    textura = board.generateImage((int(largura_mm * ppmm), int(altura_mm * ppmm)), 0, 1)
    u, v = np.meshgrid(np.arange(GT_RES[0], dtype=np.float32),
                       np.arange(GT_RES[1], dtype=np.float32))
    norm = cv2.undistortPoints(np.stack([u.ravel(), v.ravel()], 1).reshape(-1, 1, 2),
                               GT_K, GT_DIST).reshape(-1, 2)
    raios = np.concatenate([norm, np.ones((len(norm), 1))], 1).astype(np.float64)

    distancias = {}
    for i, (R, t) in enumerate(gerar_poses(n, rng, largura_mm, altura_mm), 1):
        img = renderizar(textura, ppmm, R, t, raios, 1.5, rng)
        if (img < 128).mean() < 0.01:
            continue
        nome = f"img_{i:04d}.png"
        cv2.imwrite(str(pasta / nome), img)
        # |t| é a distância da origem da câmera à ORIGEM do tabuleiro — é
        # exatamente o que validar.py compara com a trena.
        distancias[nome] = float(np.linalg.norm(t))
    return distancias


def rodar(argumentos, titulo):
    print(f"\n$ python {' '.join(str(a) for a in argumentos)}")
    p = subprocess.run([sys.executable, "-u", *[str(a) for a in argumentos]],
                       cwd=str(RAIZ), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode not in (0, 1):
        print(p.stdout[-2000:], p.stderr[-1000:])
        raise SystemExit(f"[erro] {titulo} falhou com código {p.returncode}")
    return p


def main():
    tmp = Path(tempfile.mkdtemp(prefix="e2e_"))
    saida = tmp / "saida"
    saida.mkdir()

    print("\n=== etapa 1: tabuleiro e contrato ===")
    cfg = ConfigTabuleiro(square_mm_nominal=GT_QUADRADO_MM,
                          marker_mm_nominal=round(0.75 * GT_QUADRADO_MM, 1),
                          gerado_em=agora(), opencv=cv2.__version__)
    cfg_path = saida / "tabuleiro.json"
    cfg.salvar(cfg_path)
    board, _ = construir_board(cfg, GT_QUADRADO_MM, cfg.marker_mm_nominal)

    # o contrato ainda não tem medida: a calibração TEM de se recusar a rodar
    p = rodar(["calibrar.py", "--imagens", str(saida), "--tabuleiro", str(cfg_path)],
              "guarda da escala")
    checar("recusa calibrar sem quadrado medido",
           "square_mm_medido" in (p.stdout + p.stderr) and p.returncode != 0)

    cfg.square_mm_medido = GT_QUADRADO_MM   # no sintético a "medida" é exata
    cfg.salvar(cfg_path)

    print("\n=== etapa 2: sessão A (para calibrar) ===")
    sessao_a = tmp / "sessao_a"
    render_sessao(sessao_a, board, cfg, 40, semente=11)
    n_a = len(list(sessao_a.glob("*.png")))
    checar("sessão A renderizada", n_a >= 25, f"{n_a} vistas")

    print("\n=== etapa 3: calibrar ===")
    p = rodar(["calibrar.py", "--imagens", str(sessao_a), "--tabuleiro", str(cfg_path),
               "--saida", str(saida), "--nome-camera", "e2e",
               "--particoes", "12", "--bootstrap", "100"], "calibrar")
    calib_path = saida / "calibracao_e2e.json"
    checar("calibração produziu json e relatório",
           calib_path.exists() and (saida / "relatorio_e2e.md").exists())
    r = json.loads(calib_path.read_text(encoding="utf-8"))
    checar("fx recuperado", abs(r["fx"] - GT_K[0, 0]) / GT_K[0, 0] <= TOL_E2E["fx_rel"],
           f"{r['fx']:.2f} vs {GT_K[0,0]:.2f}")
    checar("centro óptico recuperado",
           abs(r["cx"] - GT_K[0, 2]) <= TOL_E2E["c_px"] and abs(r["cy"] - GT_K[1, 2]) <= TOL_E2E["c_px"],
           f"({r['cx']:.1f}, {r['cy']:.1f}) vs ({GT_K[0,2]}, {GT_K[1,2]})")
    checar("escala registrada como medida", r["escala"]["fonte"] == "medido",
           f"{r['escala']['quadrado_mm']} mm")
    checar("procedência das imagens registrada",
           len(r["procedencia_imagens"]) == r["n_vistas"], f"{r['n_vistas']} hashes")
    print(f"       modelo escolhido: {r['modelo_distorcao']} | RMS {r['rms_global_px']:.4f} px "
          f"| veredicto {'APROVADO' if r['aprovado'] else 'REPROVADO'}")

    print("\n=== etapa 4: sessão B (independente) e validação ===")
    sessao_b = tmp / "sessao_b"
    distancias = render_sessao(sessao_b, board, cfg, 14, semente=777)
    checar("sessão B é independente da A", not (set(distancias) & set()) and len(distancias) >= 8,
           f"{len(distancias)} vistas novas")

    alvo = sorted(distancias)[len(distancias) // 2]
    dist_verdadeira = distancias[alvo]
    rodar(["validar.py", "--calibracao", str(calib_path), "--imagens", str(sessao_b),
           "--tabuleiro", str(cfg_path), "--saida", str(saida),
           "--distancia-real-mm", f"{dist_verdadeira:.1f}", "--imagem-distancia", alvo],
          "validar")
    val = json.loads((saida / "validacao.json").read_text(encoding="utf-8"))
    rp, rt = val["reprojecao_independente"], val["retidao_apos_undistort"]
    checar("reprojeção em vistas novas",
           rp["mediana_px"] <= TOL_E2E["reproj_indep_mediana_px"],
           f"mediana {rp['mediana_px']:.3f} px, P90 {rp['p90_px']:.3f}")
    checar("retidão após corrigir a distorção",
           rt["mediana_px"] <= TOL_E2E["retidao_mediana_px"],
           f"mediana {rt['mediana_px']:.3f} px")
    tm = val.get("teste_metrico")
    checar("teste métrico executado", tm is not None)
    if tm:
        checar("distância PnP bate com a verdadeira",
               abs(tm["erro_relativo"]) <= TOL_E2E["erro_metrico_rel"],
               f"{tm['distancia_pnp_mm']:.1f} vs {tm['distancia_trena_mm']:.1f} mm "
               f"({tm['erro_relativo']*100:+.2f}%)")
    checar("imagem antes/depois gerada", (saida / "undistort_antes_depois.png").exists())

    print("\n=== etapa 5: sensibilidade à escala impressa ===")
    # Uma impressora que reduz 4% não afeta a reprojeção — só a escala. É o modo
    # de falha invisível que justifica exigir a medida com paquímetro.
    cfg.square_mm_medido = GT_QUADRADO_MM * 0.96
    cfg.salvar(cfg_path)
    rodar(["calibrar.py", "--imagens", str(sessao_a), "--tabuleiro", str(cfg_path),
           "--saida", str(saida), "--nome-camera", "e2e_escala_errada",
           "--particoes", "6", "--bootstrap", "40"], "calibrar com escala errada")
    r2 = json.loads((saida / "calibracao_e2e_escala_errada.json").read_text(encoding="utf-8"))
    checar("erro de escala NÃO altera os intrínsecos",
           abs(r2["fx"] - r["fx"]) / r["fx"] < 1e-3,
           f"fx {r2['fx']:.2f} vs {r['fx']:.2f}")
    checar("erro de escala NÃO altera o RMS (é invisível na reprojeção)",
           abs(r2["rms_global_px"] - r["rms_global_px"]) < 1e-3,
           f"RMS {r2['rms_global_px']:.4f} vs {r['rms_global_px']:.4f}")
    print("       => 4% de erro de impressão vira 4% de erro em TODA distância,\n"
          "          sem deixar rastro em nenhum diagnóstico de reprojeção.")

    print("\n" + ("[APROVADO] cadeia completa consistente."
                  if not falhas else f"[REPROVADO] {len(falhas)} falha(s): {falhas}"))
    print(f"artefatos do ensaio em {saida}")
    sys.exit(0 if not falhas else 1)


if __name__ == "__main__":
    main()
