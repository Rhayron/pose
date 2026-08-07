"""
Validação INDEPENDENTE da calibração, em dados que não a produziram.

O erro de reprojeção do próprio ajuste é otimista por construção. Aqui há três
provas que não usam os dados do ajuste:

  A. Reprojeção em uma SESSÃO NOVA (capture ~10 vistas separadas).
  B. RETIDÃO: depois de corrigir a distorção, uma fileira de cantos do
     tabuleiro tem de ser reta. Mede o resíduo do ajuste de reta em px.
     Independe totalmente da escala métrica.
  C. DISTÂNCIA: você mede com trena a distância do plano do tabuleiro à lente
     e compara com o |t| da pose. É o único teste que confronta o milímetro
     estimado com um milímetro do mundo.

Os três continuam valendo para um intrínseco IMPORTADO. Na verdade valem mais:
a prova C é a única que confronta o milímetro estimado com um milímetro do
mundo, e é ela que pega um erro de escala que a reprojeção sozinha esconde —
o `solvePnP` absorve fx errado na profundidade sem elevar o resíduo.

Uso:
    python validar.py --calibracao perfis_ativos/s600.json \
                      --imagens capturas/validacao
    python validar.py ... --distancia-real-mm 600 --imagem-distancia img_0003.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from nucleo import (
    ConfigTabuleiro,
    agora,
    construir_board,
    detectar,
    escala_efetiva,
    novo_detector,
)


def carregar_intrinsecos(caminho: Path):
    """Lê K, distorção e resolução de um perfil ativo ou de um JSON plano.

    Dois formatos são aceitos porque têm garantias diferentes, e a diferença
    precisa aparecer na tela em vez de ficar implícita:

      * perfil ativo selado (`pose.active_external_camera_intrinsics`) — tem
        selo SHA-256 conferido na leitura e estado de transferência;
      * JSON plano com `K`, `dist` e `resolucao` — sem selo. Aceito para
        inspeção pontual, nunca é tratado como equivalente.
    """
    raw = json.loads(caminho.read_text(encoding="utf-8"))
    nome = raw.get("schema", {}).get("name") if isinstance(raw.get("schema"), dict) else None

    if nome == "pose.active_external_camera_intrinsics":
        from caliscope_import import carregar_perfil_ativo

        # exigir_transferencia=False de propósito: validar.py é uma das provas
        # que decidem se a transferência vale, então não pode depender dela.
        dados = carregar_perfil_ativo(caminho, exigir_transferencia=False)
        estado = dados["transferencia"]["status"]
        origem = (
            f"perfil selado {dados['camera_key']} "
            f"{dados['image_size'][0]}x{dados['image_size'][1]}, "
            f"activation_id={dados['activation_id'][:12]}, transferência={estado}"
        )
        return (
            np.array(dados["K"], np.float64),
            np.array(dados["dist"], np.float64).reshape(1, -1),
            tuple(dados["image_size"]),
            origem,
        )

    if not {"K", "dist", "resolucao"} <= set(raw):
        raise SystemExit(
            f"{caminho} não é perfil ativo nem JSON plano com K/dist/resolucao"
        )
    return (
        np.array(raw["K"], np.float64),
        np.array(raw["dist"], np.float64).reshape(1, -1),
        tuple(raw["resolucao"]),
        f"JSON plano SEM selo: {caminho.name}",
    )


def retidao(cantos_ids, cantos_px, K, dist, squares_x):
    """Resíduo (px) do ajuste de reta às fileiras de cantos, após undistort.

    O canto ChArUco de índice i está na linha i // (squares_x - 1).
    """
    pts = cv2.undistortPoints(cantos_px.reshape(-1, 1, 2), K, dist, P=K).reshape(-1, 2)
    ids = cantos_ids.ravel()
    residuos = []
    for linha in np.unique(ids // (squares_x - 1)):
        sel = pts[ids // (squares_x - 1) == linha]
        if len(sel) < 4:
            continue
        # reta por PCA: resíduo = componente ortogonal
        c = sel.mean(0)
        u = np.linalg.svd(sel - c)[2][0]
        n = np.array([-u[1], u[0]])
        residuos.append(np.abs((sel - c) @ n))
    return np.concatenate(residuos) if residuos else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calibracao", required=True)
    ap.add_argument("--imagens", required=True, help="pasta com vistas NOVAS")
    ap.add_argument("--tabuleiro", default="saida/tabuleiro.json")
    ap.add_argument("--saida", default="saida")
    ap.add_argument("--min-cantos", type=int, default=12)
    ap.add_argument("--distancia-real-mm", type=float, default=None,
                    help="distância medida com trena do plano do tabuleiro à lente")
    ap.add_argument("--imagem-distancia", default=None,
                    help="nome do arquivo onde essa distância foi medida")
    args = ap.parse_args()

    K, dist, resolucao, origem = carregar_intrinsecos(Path(args.calibracao))
    print(f"[..] intrínsecos: {origem}")

    cfg = ConfigTabuleiro.carregar(Path(args.tabuleiro))
    quadrado, marcador, _ = escala_efetiva(cfg, permitir_nominal=True)
    board, _ = construir_board(cfg, quadrado, marcador)
    detector = novo_detector(board)

    pasta = Path(args.imagens)
    arquivos = sorted(p for p in pasta.iterdir()
                      if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".tif"))
    if not arquivos:
        raise SystemExit(f"[erro] nenhuma imagem em {pasta}")
    if pasta.resolve() == Path(calib.get("_pasta_ajuste", "___")).resolve():
        print("[aviso] esta é a mesma pasta do ajuste — não é validação independente")

    reproj, ret_res, por_imagem, dist_pnp = [], [], [], None
    for caminho in arquivos:
        img = cv2.imread(str(caminho))
        if img is None:
            continue
        if (img.shape[1], img.shape[0]) != resolucao:
            raise SystemExit(
                f"[erro] {caminho.name} está em {img.shape[1]}x{img.shape[0]} e a calibração "
                f"vale para {resolucao[0]}x{resolucao[1]}. Intrínsecos não escalam entre modos."
            )
        cantos, ids = detectar(detector, img)
        if cantos is None or len(ids) < args.min_cantos:
            continue
        objp, imgp = board.matchImagePoints(cantos, ids)
        ok, rvec, tvec = cv2.solvePnP(objp, imgp, K, dist)
        if not ok:
            continue
        proj, _ = cv2.projectPoints(objp, rvec, tvec, K, dist)
        e = np.linalg.norm(proj.reshape(-1, 2) - imgp.reshape(-1, 2), axis=1)
        reproj.append(e)
        r = retidao(ids, cantos, K, dist, cfg.squares_x)
        if r is not None:
            ret_res.append(r)
        d_mm = float(np.linalg.norm(tvec))
        por_imagem.append({"arquivo": caminho.name, "n_cantos": int(len(ids)),
                           "erro_mediano_px": round(float(np.median(e)), 4),
                           "erro_p90_px": round(float(np.percentile(e, 90)), 4),
                           "distancia_pnp_mm": round(d_mm, 1)})
        if args.imagem_distancia and caminho.name == args.imagem_distancia:
            dist_pnp = d_mm

    if not reproj:
        raise SystemExit("[erro] nenhuma vista válida no conjunto de validação")

    E = np.concatenate(reproj)
    R = np.concatenate(ret_res) if ret_res else np.array([np.nan])

    # comparação visual: original vs corrigida
    primeira = cv2.imread(str(arquivos[0]))
    novaK, _ = cv2.getOptimalNewCameraMatrix(K, dist, resolucao, 1, resolucao)
    corrigida = cv2.undistort(primeira, K, dist, None, novaK)
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(saida / "undistort_antes_depois.png"), np.hstack([primeira, corrigida]))

    rel = {
        "calibracao": str(args.calibracao),
        "conjunto_validacao": str(pasta),
        "n_vistas": len(por_imagem),
        "reprojecao_independente": {
            "mediana_px": round(float(np.median(E)), 4),
            "p90_px": round(float(np.percentile(E, 90)), 4),
            "max_px": round(float(E.max()), 4),
            "frac_acima_1px": round(float((E > 1.0).mean()), 4),
        },
        "retidao_apos_undistort": {
            "mediana_px": round(float(np.nanmedian(R)), 4),
            "p90_px": round(float(np.nanpercentile(R, 90)), 4),
            "max_px": round(float(np.nanmax(R)), 4),
        },
        "por_imagem": por_imagem,
        "gerado_em": agora(),
    }
    if args.distancia_real_mm and dist_pnp:
        erro_mm = dist_pnp - args.distancia_real_mm
        rel["teste_metrico"] = {
            "imagem": args.imagem_distancia,
            "distancia_trena_mm": args.distancia_real_mm,
            "distancia_pnp_mm": round(dist_pnp, 1),
            "erro_mm": round(erro_mm, 1),
            "erro_relativo": round(erro_mm / args.distancia_real_mm, 4),
            "nota": "erro relativo ~ erro de escala do tabuleiro impresso; a trena "
                    "tem incerteza própria (medir da lente, não do corpo da câmera)",
        }

    (saida / "validacao.json").write_text(json.dumps(rel, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n--- validação independente ({len(por_imagem)} vistas novas) ---")
    print(f"reprojeção  mediana {rel['reprojecao_independente']['mediana_px']:.3f} px | "
          f"P90 {rel['reprojecao_independente']['p90_px']:.3f} | "
          f">1px {rel['reprojecao_independente']['frac_acima_1px']*100:.1f}%")
    print(f"retidão     mediana {rel['retidao_apos_undistort']['mediana_px']:.3f} px | "
          f"P90 {rel['retidao_apos_undistort']['p90_px']:.3f} "
          f"(0 = linhas perfeitamente retas após corrigir a distorção)")
    if "teste_metrico" in rel:
        t = rel["teste_metrico"]
        print(f"métrico     PnP {t['distancia_pnp_mm']:.0f} mm vs trena {t['distancia_trena_mm']:.0f} mm "
              f"=> {t['erro_mm']:+.0f} mm ({t['erro_relativo']*100:+.2f}%)")
    else:
        print("métrico     não executado (passe --distancia-real-mm e --imagem-distancia)")
    print(f"\n[ok] {saida / 'validacao.json'}")
    print(f"[ok] {saida / 'undistort_antes_depois.png'}")


if __name__ == "__main__":
    main()
