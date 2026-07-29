"""
Calibração intrínseca (em ar) com seleção de modelo e incerteza declarada.

Três decisões metodológicas, todas herdadas das lições dos ciclos v2/v3 do
detector fiducial:

 1. O MODELO DE DISTORÇÃO É ESCOLHIDO POR ERRO EM DADOS NÃO USADOS NO AJUSTE.
    O RMS de reprojeção sempre cai ao adicionar coeficientes — escolher por ele
    seleciona sobreajuste com certeza. Aqui candidatos {k1k2, k1k2+tang,
    +k3, racional} competem por erro mediano em vistas retidas (hold-out),
    em repetidas partições aleatórias, e vence o MAIS SIMPLES que fica dentro
    da tolerância do melhor (parcimônia).

 2. NENHUM NÚMERO É REPORTADO SEM DISPERSÃO. A auditoria v2 mostrou que média
    esconde outliers catastróficos: aqui sai mediana, P90, máximo e a fração
    de cantos > 1 px, por vista e no agregado. Os intrínsecos saem com IC 95%
    por bootstrap sobre as vistas (a incerteza que importa é entre-vistas,
    não entre-cantos).

 3. A RÉGUA ESTÁ FIXADA NO TOPO DESTE ARQUIVO, ANTES DE QUALQUER MEDIÇÃO.
    Alterá-la depois de ver os resultados invalida o teste.

Uso:
    python calibrar.py --imagens capturas/20260729_101500
    python calibrar.py --imagens capturas/... --bootstrap 200 --nome-camera webcam_pc
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
    ambiente,
    classificar,
    cobertura_atende,
    construir_board,
    detectar,
    escala_efetiva,
    inclinacao_graus,
    novo_detector,
    resumo_cobertura,
    sha256_arquivo,
)

# =========================================================================
# RÉGUA PRÉ-REGISTRADA — fixada em 29/07/2026, antes da primeira captura.
# Mudar qualquer valor abaixo DEPOIS de ver um resultado é mover a régua.
# Se um critério falhar, o correto é recapturar, não relaxar o número.
# =========================================================================
CRITERIOS = {
    "n_vistas_min": 25,            # graus de liberdade suficientes p/ 8-9 parâmetros
    "cobertura_completa": True,    # 9 células, 3 escalas, inclinações (ver nucleo.py)
    "rms_global_px_max": 0.50,
    "p90_erro_canto_px_max": 1.00,
    "erro_mediano_holdout_px_max": 0.60,   # generalização, não ajuste
    "largura_relativa_ic95_fx_max": 0.02,  # 2% — precisão dos intrínsecos
}
# Diagnósticos: informam, não reprovam (podem ter causa física legítima).
DIAGNOSTICOS = {
    "assimetria_fx_fy_max": 0.02,      # pixels não-quadrados, ou escala anisotrópica
    "desvio_centro_optico_max": 0.10,  # |c - centro| / dimensão
}

SEMENTE = 123  # mesma semente dos protocolos anteriores do projeto

MODELOS = [
    ("k1k2", cv2.CALIB_FIX_K3 | cv2.CALIB_ZERO_TANGENT_DIST),
    ("k1k2_tang", cv2.CALIB_FIX_K3),
    ("k1k2k3_tang", 0),
    ("racional", cv2.CALIB_RATIONAL_MODEL),
]
TOLERANCIA_PARCIMONIA_PX = 0.02  # empate técnico -> vence o modelo mais simples

CRITERIO_OTIM = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 200, 1e-9)


# -------------------------------------------------------------------------
def coletar(imagens, board, detector, min_cantos):
    dados, descartadas = [], []
    tamanho = None
    for caminho in imagens:
        img = cv2.imread(str(caminho))
        if img is None:
            descartadas.append((caminho.name, "não pôde ser lida"))
            continue
        if tamanho is None:
            tamanho = (img.shape[1], img.shape[0])
        elif (img.shape[1], img.shape[0]) != tamanho:
            raise SystemExit(
                f"[erro] {caminho.name} tem {img.shape[1]}x{img.shape[0]}, "
                f"mas as anteriores têm {tamanho[0]}x{tamanho[1]}.\n"
                f"       Intrínsecos são específicos da resolução — não misture."
            )
        cantos, ids = detectar(detector, img)
        if cantos is None or len(ids) < min_cantos:
            descartadas.append((caminho.name, f"cantos={0 if ids is None else len(ids)} < {min_cantos}"))
            continue
        objp, imgp = board.matchImagePoints(cantos, ids)
        if objp is None or len(objp) < min_cantos:
            descartadas.append((caminho.name, "matchImagePoints insuficiente"))
            continue
        tilt = inclinacao_graus(board, cantos, ids, img.shape)
        dados.append({
            "arquivo": caminho.name,
            "caminho": caminho,
            "objp": np.asarray(objp, np.float32),
            "imgp": np.asarray(imgp, np.float32),
            "n_cantos": int(len(objp)),
            "tilt_graus": round(tilt, 1),
            **classificar(cantos, img.shape, tilt),
        })
    return dados, descartadas, tamanho


def ajustar(dados, idx, tamanho, flags):
    objs = [dados[i]["objp"] for i in idx]
    imgs = [dados[i]["imgp"] for i in idx]
    return cv2.calibrateCamera(objs, imgs, tamanho, None, None, flags=flags,
                               criteria=CRITERIO_OTIM)


def erro_por_canto(dado, K, dist):
    """Erro em uma vista NÃO usada no ajuste: pose própria, intrínsecos dados."""
    ok, rvec, tvec = cv2.solvePnP(dado["objp"], dado["imgp"], K, dist,
                                  flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None
    proj, _ = cv2.projectPoints(dado["objp"], rvec, tvec, K, dist)
    return np.linalg.norm(proj.reshape(-1, 2) - dado["imgp"].reshape(-1, 2), axis=1)


def selecionar_modelo(dados, tamanho, n_particoes, rng):
    n = len(dados)
    n_treino = max(6, int(round(0.7 * n)))
    particoes = []
    for _ in range(n_particoes):
        perm = rng.permutation(n)
        particoes.append((perm[:n_treino], perm[n_treino:]))

    resultados = []
    for nome, flags in MODELOS:
        erros = []
        falhas = 0
        for treino, teste in particoes:
            try:
                _, K, dist, _, _ = ajustar(dados, treino, tamanho, flags)
            except cv2.error:
                falhas += 1
                continue
            for i in teste:
                e = erro_por_canto(dados[i], K, dist)
                if e is not None:
                    erros.append(e)
        if not erros:
            resultados.append({"modelo": nome, "falhou": True})
            continue
        todos = np.concatenate(erros)
        resultados.append({
            "modelo": nome,
            "n_coef": {"k1k2": 2, "k1k2_tang": 4, "k1k2k3_tang": 5, "racional": 8}[nome],
            "holdout_mediana_px": round(float(np.median(todos)), 4),
            "holdout_p90_px": round(float(np.percentile(todos, 90)), 4),
            "holdout_frac_acima_1px": round(float((todos > 1.0).mean()), 4),
            "ajustes_falhos": falhas,
        })

    validos = [r for r in resultados if not r.get("falhou")]
    if not validos:
        raise SystemExit("[erro] nenhum modelo convergiu — dados insuficientes ou degenerados")
    melhor = min(r["holdout_mediana_px"] for r in validos)
    # parcimônia: o primeiro (mais simples) dentro da tolerância do melhor
    escolhido = next(r for r in validos
                     if r["holdout_mediana_px"] <= melhor + TOLERANCIA_PARCIMONIA_PX)
    return escolhido, resultados, {"n_particoes": n_particoes, "frac_treino": 0.7,
                                   "tolerancia_px": TOLERANCIA_PARCIMONIA_PX}


def bootstrap_ic(dados, tamanho, flags, B, rng):
    """IC 95% por reamostragem DE VISTAS (a fonte dominante de variabilidade)."""
    n = len(dados)
    amostras = []
    for _ in range(B):
        idx = rng.integers(0, n, n)
        if len(set(idx.tolist())) < 6:
            continue
        try:
            _, K, dist, _, _ = ajustar(dados, idx, tamanho, flags)
        except cv2.error:
            continue
        d = dist.ravel()
        amostras.append([K[0, 0], K[1, 1], K[0, 2], K[1, 2],
                         d[0] if len(d) > 0 else 0.0, d[1] if len(d) > 1 else 0.0])
    if len(amostras) < 20:
        return None
    a = np.asarray(amostras)
    nomes = ["fx", "fy", "cx", "cy", "k1", "k2"]
    return {
        nome: {
            "mediana": round(float(np.median(a[:, i])), 5),
            "ic95": [round(float(np.percentile(a[:, i], 2.5)), 5),
                     round(float(np.percentile(a[:, i], 97.5)), 5)],
        }
        for i, nome in enumerate(nomes)
    }, len(amostras)


# -------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--imagens", required=True, help="pasta com as vistas (PNG/JPG)")
    ap.add_argument("--tabuleiro", default="saida/tabuleiro.json")
    ap.add_argument("--saida", default="saida")
    ap.add_argument("--nome-camera", default="webcam_pc")
    ap.add_argument("--min-cantos", type=int, default=12)
    ap.add_argument("--particoes", type=int, default=20)
    ap.add_argument("--bootstrap", type=int, default=150)
    ap.add_argument("--assumir-nominal", action="store_true",
                    help="usa o quadrado NOMINAL; marca o resultado como não rastreável")
    args = ap.parse_args()

    rng = np.random.default_rng(SEMENTE)
    cfg = ConfigTabuleiro.carregar(Path(args.tabuleiro))
    quadrado, marcador, fonte_escala = escala_efetiva(cfg, args.assumir_nominal)
    board, _ = construir_board(cfg, quadrado, marcador)
    detector = novo_detector(board)

    pasta = Path(args.imagens)
    arquivos = sorted([p for p in pasta.iterdir()
                       if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".tif")])
    if not arquivos:
        raise SystemExit(f"[erro] nenhuma imagem em {pasta}")
    if any(p.suffix.lower() in (".jpg", ".jpeg") for p in arquivos):
        print("[aviso] há JPEG no conjunto. Compressão com perdas desloca cantos em\n"
              "        fração de pixel — a mesma grandeza que estamos medindo.")

    print(f"[..] detectando o tabuleiro em {len(arquivos)} imagens")
    dados, descartadas, tamanho = coletar(arquivos, board, detector, args.min_cantos)
    print(f"[ok] {len(dados)} vistas aceitas, {len(descartadas)} descartadas")
    for nome, motivo in descartadas:
        print(f"     - {nome}: {motivo}")
    if len(dados) < 6:
        raise SystemExit("[erro] menos de 6 vistas úteis — impossível calibrar com honestidade")

    resumo_cob = resumo_cobertura(dados)
    cob_ok, cob_faltas = cobertura_atende(resumo_cob)

    print(f"[..] selecionando o modelo de distorção ({args.particoes} partições hold-out)")
    escolhido, comparacao, protocolo_sel = selecionar_modelo(dados, tamanho, args.particoes, rng)
    flags = dict(MODELOS)[escolhido["modelo"]]
    print(f"[ok] modelo escolhido: {escolhido['modelo']} "
          f"(hold-out mediana {escolhido['holdout_mediana_px']:.3f} px)")
    for r in comparacao:
        if not r.get("falhou"):
            marca = "<<" if r["modelo"] == escolhido["modelo"] else "  "
            print(f"     {marca} {r['modelo']:14s} coef={r['n_coef']}  "
                  f"mediana={r['holdout_mediana_px']:.3f}  P90={r['holdout_p90_px']:.3f}  "
                  f">1px={r['holdout_frac_acima_1px']*100:.1f}%")

    print("[..] ajuste final com todas as vistas")
    todas = np.arange(len(dados))
    try:
        (rms, K, dist, rvecs, tvecs, std_int, _, _erros_vista) = cv2.calibrateCameraExtended(
            [d["objp"] for d in dados], [d["imgp"] for d in dados], tamanho, None, None,
            flags=flags, criteria=CRITERIO_OTIM)
        std_int = np.asarray(std_int).ravel()
    except AttributeError:
        rms, K, dist, rvecs, tvecs = ajustar(dados, todas, tamanho, flags)
        std_int = None

    # distribuição do erro por canto, no ajuste completo
    por_vista, todos_erros = [], []
    for i, d in enumerate(dados):
        proj, _ = cv2.projectPoints(d["objp"], rvecs[i], tvecs[i], K, dist)
        e = np.linalg.norm(proj.reshape(-1, 2) - d["imgp"].reshape(-1, 2), axis=1)
        todos_erros.append(e)
        por_vista.append({
            "arquivo": d["arquivo"], "n_cantos": d["n_cantos"], "tilt_graus": d["tilt_graus"],
            "escala": d["escala"], "celula": d["celula"],
            "erro_mediano_px": round(float(np.median(e)), 4),
            "erro_p90_px": round(float(np.percentile(e, 90)), 4),
            "erro_max_px": round(float(e.max()), 4),
            "distancia_mm": round(float(np.linalg.norm(tvecs[i])), 1),
        })
    E = np.concatenate(todos_erros)
    erro = {
        "n_cantos_total": int(E.size),
        "mediana_px": round(float(np.median(E)), 4),
        "p90_px": round(float(np.percentile(E, 90)), 4),
        "p99_px": round(float(np.percentile(E, 99)), 4),
        "max_px": round(float(E.max()), 4),
        "frac_acima_1px": round(float((E > 1.0).mean()), 4),
    }
    lim = float(np.percentile([v["erro_mediano_px"] for v in por_vista], 95))
    suspeitas = [v["arquivo"] for v in por_vista if v["erro_mediano_px"] > max(lim, 2 * erro["mediana_px"])]

    print(f"[..] bootstrap de incerteza (B={args.bootstrap})")
    boot = bootstrap_ic(dados, tamanho, flags, args.bootstrap, rng)
    ic, n_boot = boot if boot else (None, 0)

    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    largura_ic_fx = (ic["fx"]["ic95"][1] - ic["fx"]["ic95"][0]) / fx if ic else float("nan")
    fov_x, fov_y, dist_focal_mm, ponto_principal, aspecto = cv2.calibrationMatrixValues(
        K, tamanho, float(tamanho[0]), float(tamanho[1]))

    veredicto = {
        "n_vistas_min": (len(dados) >= CRITERIOS["n_vistas_min"], f"{len(dados)} >= {CRITERIOS['n_vistas_min']}"),
        "cobertura_completa": (cob_ok, "; ".join(cob_faltas) or "completa"),
        "rms_global_px_max": (rms <= CRITERIOS["rms_global_px_max"], f"{rms:.4f} <= {CRITERIOS['rms_global_px_max']}"),
        "p90_erro_canto_px_max": (erro["p90_px"] <= CRITERIOS["p90_erro_canto_px_max"],
                                  f"{erro['p90_px']:.4f} <= {CRITERIOS['p90_erro_canto_px_max']}"),
        "erro_mediano_holdout_px_max": (escolhido["holdout_mediana_px"] <= CRITERIOS["erro_mediano_holdout_px_max"],
                                        f"{escolhido['holdout_mediana_px']:.4f} <= {CRITERIOS['erro_mediano_holdout_px_max']}"),
        "largura_relativa_ic95_fx_max": (bool(largura_ic_fx <= CRITERIOS["largura_relativa_ic95_fx_max"]),
                                         f"{largura_ic_fx*100:.2f}% <= {CRITERIOS['largura_relativa_ic95_fx_max']*100:.0f}%"),
    }
    diagnostico = {
        "assimetria_fx_fy": (abs(fx - fy) / fx, DIAGNOSTICOS["assimetria_fx_fy_max"]),
        "desvio_cx": (abs(cx - tamanho[0] / 2) / tamanho[0], DIAGNOSTICOS["desvio_centro_optico_max"]),
        "desvio_cy": (abs(cy - tamanho[1] / 2) / tamanho[1], DIAGNOSTICOS["desvio_centro_optico_max"]),
    }
    aprovado = all(ok for ok, _ in veredicto.values())

    sessao_json = pasta / "sessao.json"
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    resultado = {
        "camera": args.nome_camera,
        "resolucao": list(tamanho),
        "unidade": "mm",
        "escala": {"quadrado_mm": quadrado, "marcador_mm": marcador, "fonte": fonte_escala},
        "modelo_distorcao": escolhido["modelo"],
        "K": K.tolist(),
        "dist": dist.ravel().tolist(),
        "fx": fx, "fy": fy, "cx": cx, "cy": cy,
        "fov_graus": {"x": round(fov_x, 3), "y": round(fov_y, 3)},
        "aspecto_pixel": round(aspecto, 6),
        "rms_global_px": round(float(rms), 4),
        "erro_reprojecao": erro,
        "desvio_padrao_intrinsecos": (np.asarray(std_int).ravel().tolist() if std_int is not None else None),
        "ic95_bootstrap": ic,
        "n_amostras_bootstrap": n_boot,
        "selecao_modelo": {"escolhido": escolhido, "comparacao": comparacao, "protocolo": protocolo_sel},
        "n_vistas": len(dados),
        "vistas_descartadas": [{"arquivo": n, "motivo": m} for n, m in descartadas],
        "vistas_suspeitas": suspeitas,
        "por_vista": por_vista,
        "cobertura": resumo_cob,
        "cobertura_atende": cob_ok,
        "criterios_pre_registrados": CRITERIOS,
        "veredicto": {k: {"aprovado": bool(v[0]), "medido": v[1]} for k, v in veredicto.items()},
        "diagnosticos": {k: {"valor": round(float(v), 5), "limite": lim_}
                         for k, (v, lim_) in diagnostico.items()},
        "aprovado": bool(aprovado),
        "semente": SEMENTE,
        "tabuleiro": json.loads(Path(args.tabuleiro).read_text(encoding="utf-8")),
        "sessao_captura": (json.loads(sessao_json.read_text(encoding="utf-8"))
                           if sessao_json.exists() else None),
        "procedencia_imagens": {d["arquivo"]: sha256_arquivo(d["caminho"])[:16] for d in dados},
        "ambiente": ambiente(),
        "gerado_em": agora(),
    }
    destino = saida / f"calibracao_{args.nome_camera}.json"
    destino.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- relatório legível -------------------------------------------------
    linhas = [
        f"# Calibração intrínseca — {args.nome_camera}",
        "",
        f"**Data:** {agora()} · **Resolução:** {tamanho[0]}x{tamanho[1]} · "
        f"**Vistas:** {len(dados)} · **Semente:** {SEMENTE}",
        f"**Escala métrica:** quadrado = {quadrado:g} mm (fonte: **{fonte_escala}**)",
        "",
        "## Intrínsecos",
        "",
        "| Parâmetro | Valor | IC 95% (bootstrap sobre vistas) |",
        "| :--- | ---: | :--- |",
    ]
    for nome, valor in (("fx", fx), ("fy", fy), ("cx", cx), ("cy", cy)):
        faixa = f"[{ic[nome]['ic95'][0]:.2f}, {ic[nome]['ic95'][1]:.2f}]" if ic else "n/d"
        linhas.append(f"| {nome} | {valor:.3f} | {faixa} |")
    linhas += [
        "",
        f"Modelo de distorção escolhido: **{escolhido['modelo']}** · "
        f"coeficientes: `{[round(v, 6) for v in dist.ravel().tolist()]}`",
        f"FOV: {fov_x:.1f}° x {fov_y:.1f}° · razão de aspecto do pixel: {aspecto:.5f}",
        "",
        "## Seleção do modelo (erro em vistas retidas)",
        "",
        "| Modelo | coef. | mediana (px) | P90 (px) | >1 px |",
        "| :--- | ---: | ---: | ---: | ---: |",
    ]
    for r in comparacao:
        if r.get("falhou"):
            linhas.append(f"| {r['modelo']} | — | não convergiu | — | — |")
        else:
            m = "**" if r["modelo"] == escolhido["modelo"] else ""
            linhas.append(f"| {m}{r['modelo']}{m} | {r['n_coef']} | {r['holdout_mediana_px']:.3f} "
                          f"| {r['holdout_p90_px']:.3f} | {r['holdout_frac_acima_1px']*100:.1f}% |")
    linhas += [
        "",
        f"Protocolo: {protocolo_sel['n_particoes']} partições aleatórias 70/30, "
        f"vence o modelo mais simples dentro de {TOLERANCIA_PARCIMONIA_PX} px do melhor.",
        "",
        "## Erro de reprojeção (ajuste completo)",
        "",
        f"RMS global {rms:.4f} px · mediana {erro['mediana_px']:.3f} · "
        f"P90 {erro['p90_px']:.3f} · P99 {erro['p99_px']:.3f} · máx {erro['max_px']:.3f} · "
        f"{erro['frac_acima_1px']*100:.2f}% dos cantos acima de 1 px",
        "",
        f"Vistas suspeitas (erro mediano atípico): {suspeitas or 'nenhuma'}",
        "",
        "## Veredicto contra a régua pré-registrada",
        "",
        "| Critério | Medido | Resultado |",
        "| :--- | :--- | :--- |",
    ]
    for k, (ok, txt) in veredicto.items():
        linhas.append(f"| {k} | {txt} | {'APROVADO' if ok else '**REPROVADO**'} |")
    linhas += ["", "Diagnósticos (informativos, não reprovam):", ""]
    for k, (v, lim_) in diagnostico.items():
        linhas.append(f"- {k} = {v:.4f} (referência {lim_})")
    linhas += [
        "",
        f"**Situação: {'APROVADA' if aprovado else 'REPROVADA — recapturar, não relaxar o critério'}**",
        "",
        "## Limites de validade",
        "",
        f"- Válida SOMENTE para esta câmera, em {tamanho[0]}x{tamanho[1]}, com os mesmos ajustes de",
        "  foco/exposição/zoom registrados em `sessao_captura` neste arquivo. Qualquer mudança",
        "  (inclusive trocar a resolução do software) invalida fx, fy, cx, cy.",
        "- Calibração **em ar**. Não descreve o caminho ar–vidro–água do tanque: aplicá-la",
        "  submersa produz erro sistemático — que é justamente o que H₂ se propõe a medir.",
        "  Esta calibração é a condição de controle (pinhole) do Experimento 3.",
    ]
    (saida / f"relatorio_{args.nome_camera}.md").write_text("\n".join(linhas), encoding="utf-8")

    print("\n" + "\n".join(linhas[-40:]))
    print(f"\n[ok] {destino}")
    print(f"[ok] {saida / f'relatorio_{args.nome_camera}.md'}")
    if not aprovado:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
