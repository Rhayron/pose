"""Testes do importador Caliscope e do gate de transferencia.

Um gate que nunca reprova nao mede nada. Estes testes verificam as duas
direcoes: que o gate aprova quando o intrinseco esta certo e que ele **reprova**
quando fx esta sistematicamente errado — que e exatamente a falha esperada se o
foco ou o FOV da S600 mudarem entre os projetos.

    python teste_caliscope.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from caliscope_import import (  # noqa: E402
    CaliscopeImportError,
    _verify_seal,
    ativar,
    carregar_perfil_ativo,
    importar_intrinsecos,
)
import validar_transferencia as vt  # noqa: E402

FALHAS: list[str] = []


def checar(condicao: bool, descricao: str) -> None:
    marca = "ok  " if condicao else "FALHA"
    print(f"  [{marca}] {descricao}")
    if not condicao:
        FALHAS.append(descricao)


# --------------------------------------------------------------------------
# Renderizacao sintetica
# --------------------------------------------------------------------------


def _tabuleiro_de(contrato: dict):
    return vt._construir_tabuleiro(contrato)


def _mapas_de_distorcao(
    K: np.ndarray, dist: np.ndarray, tamanho: tuple[int, int]
) -> tuple[np.ndarray, np.ndarray]:
    """Mapas que transformam a imagem pinhole ideal na imagem distorcida.

    Homografia sozinha nao serve: ela e linear e reproduz a distorcao apenas
    nos quatro cantos usados para ajusta-la, deixando o interior do tabuleiro
    sem distorcao. Isso introduziria um vies de escala no proprio teste — que
    e justamente a grandeza que o gate mede.

    Para cada pixel (u, v) da imagem DISTORCIDA, `undistortPoints(..., P=K)`
    devolve onde esse ponto cai na imagem ideal. E o mapa que o remap precisa.
    """
    largura, altura = tamanho
    grade = np.stack(np.meshgrid(
        np.arange(largura, dtype=np.float32),
        np.arange(altura, dtype=np.float32),
    ), axis=-1).reshape(-1, 1, 2)
    ideal = cv2.undistortPoints(grade, K, dist, P=K).reshape(altura, largura, 2)
    return ideal[..., 0].copy(), ideal[..., 1].copy()


def renderizar_vista(
    tabuleiro, K: np.ndarray, dist: np.ndarray, tamanho: tuple[int, int],
    rvec: np.ndarray, tvec: np.ndarray,
    mapas: tuple[np.ndarray, np.ndarray] | None = None,
) -> np.ndarray | None:
    """Renderiza o tabuleiro sob o modelo (K, dist, R, t) exato.

    Duas etapas separadas, na ordem fisica: projecao pinhole por homografia,
    depois distorcao radial/tangencial por remap. A imagem sai do MESMO modelo
    que o gate vai testar, entao residuo alto so pode vir de divergencia de K.
    """
    largura, altura = tamanho
    quadrado_mm = tabuleiro.getSquareLength()
    nx, ny = tabuleiro.getChessboardSize()

    # marginSize=0: a imagem gerada cobre exatamente a extensao do tabuleiro.
    # Margem > 0 faria a homografia mapear tabuleiro+margem sobre a area do
    # tabuleiro, encolhendo-o e produzindo um erro de escala sistematico.
    px_por_mm = 6
    imagem_plana = tabuleiro.generateImage(
        (int(nx * quadrado_mm * px_por_mm), int(ny * quadrado_mm * px_por_mm)),
        marginSize=0,
    )
    imagem_plana = cv2.cvtColor(imagem_plana, cv2.COLOR_GRAY2BGR)

    # getChessboardCorners() coloca o primeiro canto interno em (sq, sq), logo
    # o canto fisico do tabuleiro esta na origem e a extensao e nx*sq por ny*sq.
    cantos_mundo = np.array([
        [0.0, 0.0, 0.0],
        [nx * quadrado_mm, 0.0, 0.0],
        [nx * quadrado_mm, ny * quadrado_mm, 0.0],
        [0.0, ny * quadrado_mm, 0.0],
    ], dtype=np.float64)

    sem_distorcao = np.zeros((1, 5), dtype=np.float64)
    projetado, _ = cv2.projectPoints(cantos_mundo, rvec, tvec, K, sem_distorcao)
    projetado = projetado.reshape(-1, 2).astype(np.float32)
    if not np.isfinite(projetado).all():
        return None
    if projetado.min() < -largura or projetado.max() > 2 * largura:
        return None

    h, w = imagem_plana.shape[:2]
    origem = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(origem, projetado)
    ideal = cv2.warpPerspective(
        imagem_plana, H, (largura, altura),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255),
    )

    mapa_x, mapa_y = mapas if mapas is not None else _mapas_de_distorcao(K, dist, tamanho)
    return cv2.remap(
        ideal, mapa_x, mapa_y, interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255),
    )


def gerar_capturas(destino: Path, tabuleiro, K, dist, tamanho, n: int = 12) -> int:
    destino.mkdir(parents=True, exist_ok=True)
    mapas = _mapas_de_distorcao(K, dist, tamanho)  # constante entre as vistas
    rng = np.random.default_rng(123)
    gravadas = 0
    tentativas = 0
    while gravadas < n and tentativas < n * 12:
        tentativas += 1
        rvec = np.array([
            rng.uniform(-0.45, 0.45),
            rng.uniform(-0.45, 0.45),
            rng.uniform(-0.25, 0.25),
        ], dtype=np.float64).reshape(3, 1)
        tvec = np.array([
            rng.uniform(-70.0, 70.0),
            rng.uniform(-50.0, 50.0),
            rng.uniform(420.0, 650.0),
        ], dtype=np.float64).reshape(3, 1)
        imagem = renderizar_vista(tabuleiro, K, dist, tamanho, rvec, tvec, mapas)
        if imagem is None:
            continue
        gravadas += 1
        cv2.imwrite(str(destino / f"vista_{gravadas:02d}.png"), imagem)
    return gravadas


# --------------------------------------------------------------------------
# Testes
# --------------------------------------------------------------------------


def teste_importacao_e_selo(tmp: Path) -> Path:
    print("\n1. Importacao, selo e deteccao de adulteracao")

    imported = importar_intrinsecos(RAIZ / "caliscope-import.json")
    checar(imported.passed, "importacao aprovada nos criterios pre-registrados")
    checar(imported.profile["intrinsics"]["image_size"] == [1920, 1080],
           "intrinseco vale para 1920x1080")
    checar(imported.profile["transferencia"]["status"] == "nao_validada",
           "perfil nasce com transferencia nao validada")
    checar(
        imported.profile["external_boundary"]["internal_validation_evidence_present"]
        is False,
        "nao alega evidencia de validacao interna",
    )

    documento = tmp / "import.json"
    imported.save(documento)
    perfil = tmp / "s600.json"
    ativar(documento, perfil)

    # O carregador tem de recusar um perfil ainda nao validado na bancada.
    try:
        carregar_perfil_ativo(perfil)
        checar(False, "perfil nao validado deveria ser recusado no carregamento")
    except CaliscopeImportError:
        checar(True, "perfil nao validado e recusado no carregamento")

    checar(carregar_perfil_ativo(perfil, exigir_transferencia=False)["K"][0][0]
           == 1495.7420106987456,
           "K e legivel com exigir_transferencia=False")

    # Adulteracao de um digito de fx precisa quebrar o selo.
    raw = json.loads(perfil.read_text(encoding="utf-8"))
    raw["import_document"]["profile"]["intrinsics"]["K"][0][0] = 1600.0
    adulterado = tmp / "adulterado.json"
    adulterado.write_text(json.dumps(raw), encoding="utf-8")
    try:
        _verify_seal(json.loads(adulterado.read_text(encoding="utf-8")),
                     id_field="activation_id")
        checar(False, "selo deveria detectar fx adulterado")
    except CaliscopeImportError:
        checar(True, "selo detecta fx adulterado")

    # Adulteracao de um artefato de origem precisa quebrar a importacao.
    copia = tmp / "projeto"
    shutil.copytree(RAIZ / "origem_caliscope", copia / "origem_caliscope")
    (copia / "saida").mkdir(parents=True, exist_ok=True)
    shutil.copy(RAIZ / "saida" / "tabuleiro.json", copia / "saida" / "tabuleiro.json")
    shutil.copy(RAIZ / "caliscope-import.json", copia / "caliscope-import.json")
    alvo = copia / "origem_caliscope" / "camera_array.toml"
    alvo.write_text(
        alvo.read_text(encoding="utf-8").replace("1495.7420106987456", "1600.0"),
        encoding="utf-8",
    )
    try:
        importar_intrinsecos(copia / "caliscope-import.json")
        checar(False, "manifesto deveria reprovar camera_array alterado")
    except CaliscopeImportError as exc:
        checar("nao confere com o hash declarado" in str(exc),
               "manifesto reprova camera_array alterado")

    return perfil


def teste_gate_transferencia(tmp: Path, perfil: Path) -> None:
    print("\n2. Gate de transferencia com imagens sinteticas")

    dados = carregar_perfil_ativo(perfil, exigir_transferencia=False)
    K = np.array(dados["K"], dtype=np.float64)
    dist = np.array(dados["dist"], dtype=np.float64).reshape(1, -1)
    tamanho = tuple(dados["image_size"])

    contrato = json.loads(perfil.read_text(encoding="utf-8"))
    contrato = contrato["import_document"]["profile"]["charuco"]["contract"]
    tabuleiro, _dic, _q, _m = _tabuleiro_de(contrato)

    # --- caso A: camera realmente descrita pelo K importado ---------------
    pasta_ok = tmp / "capturas_ok"
    n = gerar_capturas(pasta_ok, tabuleiro, K, dist, tamanho, n=12)
    checar(n >= vt.CRITERIOS["n_vistas_min"], f"{n} vistas sinteticas geradas")

    relatorio = vt.validar(perfil, pasta_ok)
    m = relatorio["medidas"]
    print(f"       mediana={m['erro_mediano_px']} px  p90={m['erro_p90_px']} px  "
          f"escala_fx={m['escala_fx_refit']}")
    checar(relatorio["aprovado"], "APROVA quando o K descreve a camera")
    checar(abs(m["escala_fx_refit"] - 1.0) <= 0.02,
           "escala_fx_refit ~ 1.00 quando nao ha divergencia")

    # --- caso B: fx 5% maior, como se o foco/FOV tivessem mudado -----------
    K_mudado = K.copy()
    K_mudado[0, 0] *= 1.05
    K_mudado[1, 1] *= 1.05
    pasta_ruim = tmp / "capturas_fov_mudado"
    gerar_capturas(pasta_ruim, tabuleiro, K_mudado, dist, tamanho, n=12)

    relatorio_ruim = vt.validar(perfil, pasta_ruim)
    m2 = relatorio_ruim["medidas"]
    print(f"       mediana={m2['erro_mediano_px']} px  p90={m2['erro_p90_px']} px  "
          f"escala_fx={m2['escala_fx_refit']}")
    checar(not relatorio_ruim["aprovado"], "REPROVA quando fx diverge 5%")
    checar(abs(m2["escala_fx_refit"] - 1.05) <= 0.01,
           f"escala_fx_refit recupera o fator real ({m2['escala_fx_refit']} ~ 1.05)")
    checar(any("escala sistematica" in t for t in relatorio_ruim["interpretacao"]),
           "diagnostico aponta escala sistematica, nao ruido")

    # --- caso C: resolucao errada tem de ser falha dura -------------------
    pasta_res = tmp / "capturas_resolucao"
    pasta_res.mkdir(parents=True, exist_ok=True)
    imagem = cv2.imread(str(sorted(pasta_ok.glob("*.png"))[0]))
    cv2.imwrite(str(pasta_res / "meia.png"),
                cv2.resize(imagem, (tamanho[0] // 2, tamanho[1] // 2)))
    try:
        vt.validar(perfil, pasta_res)
        checar(False, "resolucao divergente deveria ser falha dura")
    except CaliscopeImportError as exc:
        checar("nao ha reescala" in str(exc),
               "resolucao divergente e falha dura, sem reescala implicita")


def main() -> int:
    print("Testes do importador Caliscope e do gate de transferencia")
    print(f"OpenCV {cv2.__version__} | NumPy {np.__version__} | "
          f"Python {sys.version.split()[0]}")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        perfil = teste_importacao_e_selo(tmp)
        teste_gate_transferencia(tmp, perfil)

    print()
    if FALHAS:
        print(f"{len(FALHAS)} FALHA(S):")
        for falha in FALHAS:
            print(f"  - {falha}")
        return 1
    print("Todos os testes passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
