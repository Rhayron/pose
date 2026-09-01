"""Importador estrito de intrinsecos Caliscope 0.11.3 para o projeto pose.

Porte monocular do importador do projeto `vrchat`. O que foi preservado da
metodologia original:

* documento selado por SHA-256 sobre JSON canonico (chaves ordenadas);
* manifesto de arquivos com hash recalculado na importacao — trocar qualquer
  artefato de origem muda `source_identity_sha256` e invalida a importacao;
* criterios de aceite pre-registrados, gravados dentro do proprio documento,
  para que um arquivo aprovado sob um limite seja distinguivel de outro
  aprovado sob limite diferente;
* separacao entre exposicao de **aquisicao** (geometria) e de **runtime**
  (operacao). A primeira nunca autoriza a segunda;
* fronteira externa explicita: nada aqui alega metodologia interna nem produz
  evidencia de validacao interna.

O que foi removido por ser especifico do rig estereo do vrchat: extrinseca,
baseline, cheiralidade, pareamento de sync e ativacao em par. O pose e
monocular — importar geometria de duas cameras seria carregar contrato que
nao tem como ser honrado aqui.

O que foi ACRESCENTADO e nao existia no vrchat: o conceito de *transferencia*.
Reaproveitar K medido em outro projeto e uma hipotese, nao um dado. O perfil
importado nasce com `transferencia.status = "nao_validada"` e so vira
`"validada"` depois que `validar_transferencia.py` medir reprojecao na bancada
do pose com K congelado. Nada no importador aprova a transferencia sozinho.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# tomllib e stdlib a partir do Python 3.11 (o projeto roda 3.11.15). O fallback
# para tomli existe para que o modulo continue importavel em 3.10, onde os
# testes de CI podem rodar.
try:
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - depende da versao do runtime
    try:
        import tomli as _toml  # type: ignore[no-redef]
    except ModuleNotFoundError as _exc:  # pragma: no cover
        raise ModuleNotFoundError(
            "leitura de TOML indisponivel: use Python >= 3.11 ou instale tomli"
        ) from _exc

_TOMLDecodeError = _toml.TOMLDecodeError

# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

IMPORT_CONFIG_SCHEMA = "pose.caliscope_intrinsic_import_config"
IMPORT_SCHEMA = "pose.caliscope_intrinsic_import"
PROFILE_SCHEMA = "pose.external_camera_intrinsics"
ACTIVE_PROFILE_SCHEMA = "pose.active_external_camera_intrinsics"

SCHEMA_VERSION = 1

# --------------------------------------------------------------------------
# Criterios pre-registrados
# --------------------------------------------------------------------------
#
# Herdados do caminho externo do vrchat, sem afrouxamento. O limite de 0,80 px
# vale SO para calibracao externa vinda do Caliscope; o calibrador proprio do
# pose sempre exigiu 0,50 px e esse numero nao muda por causa deste import.
# Registrar a base por escrito e o que torna os dois casos distinguiveis pela
# leitura do arquivo, sem depender de memoria de quem importou.

RMSE_PX_MAX = 0.80
RMSE_BASIS = (
    "limite do caminho externo Caliscope, herdado do projeto vrchat. Nao vale "
    "para calibracao medida dentro do pose, cujo limite pre-registrado e 0,50 px."
)

INTRINSIC_CRITERIA: dict[str, Any] = {
    "rmse_px_max": RMSE_PX_MAX,
    "rmse_px_max_basis": RMSE_BASIS,
    "frames_used_min": 20,
    "coverage_fraction_min": 0.80,
    "edge_coverage_fraction_min": 0.75,
    "corner_coverage_fraction_min": 0.50,
    "orientation_sufficient": True,
}

CHECKSUM_ASSURANCE = (
    "sha256 detecta alteracao local; nao autentica operador nem origem"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CaliscopeImportError(Exception):
    """Falha dura de importacao. Nunca e degradada em aviso."""


# --------------------------------------------------------------------------
# Primitivas de integridade
# --------------------------------------------------------------------------


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_file(path: Path, *, label: str) -> tuple[str, int]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise CaliscopeImportError(f"artefato {label} ilegivel: {path}") from exc
    if not payload:
        raise CaliscopeImportError(f"artefato {label} esta vazio: {path}")
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _require_sha256(value: object, *, field: str) -> str:
    text = str(value).lower()
    if not _SHA256_RE.fullmatch(text):
        raise CaliscopeImportError(f"{field} nao e um SHA-256 hexadecimal")
    return text


def _finite(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise CaliscopeImportError(f"{field} nao aceita booleano")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise CaliscopeImportError(f"{field} nao e numerico") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise CaliscopeImportError(f"{field} nao e finito")
    return number


def _integrity(digest: str) -> dict[str, str]:
    return {
        "algorithm": "sha256",
        "canonicalization": "json-sort-keys-v1",
        "content_sha256": digest,
        "assurance": CHECKSUM_ASSURANCE,
    }


def _seal(identity: Mapping[str, Any], *, id_field: str) -> dict[str, Any]:
    """Sela um documento: o id curto e o prefixo do digest do proprio conteudo."""
    digest = _sha256_json(identity)
    sealed = dict(identity)
    sealed[id_field] = digest[:24]
    sealed["integrity"] = _integrity(digest)
    return sealed


def _verify_seal(document: Mapping[str, Any], *, id_field: str) -> str:
    identity = {
        k: v for k, v in document.items() if k not in (id_field, "integrity")
    }
    digest = _sha256_json(identity)
    declared = document.get("integrity", {}).get("content_sha256")
    if digest != declared:
        raise CaliscopeImportError(
            f"selo invalido: recalculado {digest[:16]}..., declarado {str(declared)[:16]}..."
        )
    return digest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Leitura dos artefatos Caliscope
# --------------------------------------------------------------------------


def _load_camera_array(path: Path, cam_id: int) -> dict[str, Any]:
    """Extrai K, distorcao, tamanho e rotacao de UMA camera do camera_array.toml."""
    try:
        data = _toml.loads(path.read_text(encoding="utf-8"))
    except (OSError, _TOMLDecodeError, UnicodeDecodeError) as exc:
        raise CaliscopeImportError(f"camera_array.toml ilegivel: {exc}") from exc

    cameras = data.get("cameras")
    if not isinstance(cameras, dict):
        raise CaliscopeImportError("camera_array.toml sem tabela [cameras]")
    entry = cameras.get(str(cam_id))
    if not isinstance(entry, dict):
        disponiveis = sorted(cameras)
        raise CaliscopeImportError(
            f"camera_array.toml nao tem cam_id={cam_id}; disponiveis: {disponiveis}"
        )

    if entry.get("fisheye"):
        raise CaliscopeImportError(
            "modelo fisheye nao e suportado: o pose assume pinhole + k1k2k3_tang"
        )

    size = entry.get("size")
    if not (isinstance(size, list) and len(size) == 2):
        raise CaliscopeImportError("camera_array.toml sem 'size' [width, height]")
    width, height = int(size[0]), int(size[1])
    if width <= 0 or height <= 0:
        raise CaliscopeImportError("resolucao invalida no camera_array.toml")

    matrix = entry.get("matrix")
    if not (isinstance(matrix, list) and len(matrix) == 3
            and all(isinstance(row, list) and len(row) == 3 for row in matrix)):
        raise CaliscopeImportError("camera_array.toml sem matriz K 3x3")
    K = [[_finite(v, field="K") for v in row] for row in matrix]

    if K[0][1] != 0.0 or K[1][0] != 0.0 or K[2] != [0.0, 0.0, 1.0]:
        raise CaliscopeImportError("K nao esta na forma pinhole canonica")
    for name, value in (("fx", K[0][0]), ("fy", K[1][1])):
        if value <= 0:
            raise CaliscopeImportError(f"{name} deve ser positivo")
    if not (0 < K[0][2] < width and 0 < K[1][2] < height):
        raise CaliscopeImportError("ponto principal fora da imagem")

    dist = entry.get("distortions")
    if not (isinstance(dist, list) and len(dist) == 5):
        raise CaliscopeImportError(
            "distortions deve ter 5 coeficientes (k1, k2, p1, p2, k3)"
        )
    dist = [_finite(v, field="distortions") for v in dist]

    rotation_count = int(entry.get("rotation_count", 0))
    if rotation_count not in (0, 1, 2, 3):
        raise CaliscopeImportError("rotation_count deve estar em 0..3")

    return {
        "image_size": [width, height],
        "K": K,
        "distortion_model": "k1k2k3_tang",
        "distortion_coefficients": dist,
        "rotation_count": rotation_count,
        "bundle_error_px": _finite(entry.get("error", 0.0), field="error"),
        "grid_count": int(entry.get("grid_count", 0)),
    }


def _load_intrinsic_report(path: Path) -> dict[str, Any]:
    try:
        data = _toml.loads(path.read_text(encoding="utf-8"))
    except (OSError, _TOMLDecodeError, UnicodeDecodeError) as exc:
        raise CaliscopeImportError(f"relatorio intrinseco ilegivel: {exc}") from exc

    obrigatorios = (
        "rmse", "frames_used", "coverage_fraction",
        "edge_coverage_fraction", "corner_coverage_fraction",
        "orientation_sufficient",
    )
    faltando = [k for k in obrigatorios if k not in data]
    if faltando:
        raise CaliscopeImportError(
            "relatorio intrinseco incompleto; campos ausentes: "
            + ", ".join(faltando)
            + ". Conclua e exporte a calibracao no Caliscope; nao preencha metricas a mao."
        )
    return {
        "rmse": _finite(data["rmse"], field="rmse"),
        "frames_used": int(data["frames_used"]),
        "coverage_fraction": _finite(data["coverage_fraction"], field="coverage_fraction"),
        "edge_coverage_fraction": _finite(
            data["edge_coverage_fraction"], field="edge_coverage_fraction"),
        "corner_coverage_fraction": _finite(
            data["corner_coverage_fraction"], field="corner_coverage_fraction"),
        "orientation_sufficient": bool(data["orientation_sufficient"]),
        "orientation_count": int(data.get("orientation_count", 0)),
        "selected_frames": list(data.get("selected_frames", [])),
    }


def _load_charuco(path: Path, board_contract: Mapping[str, Any]) -> dict[str, Any]:
    """Confere que o tabuleiro do Caliscope descreve o mesmo tabuleiro fisico."""
    try:
        data = _toml.loads(path.read_text(encoding="utf-8"))
    except (OSError, _TOMLDecodeError, UnicodeDecodeError) as exc:
        raise CaliscopeImportError(f"charuco.toml ilegivel: {exc}") from exc

    divergencias: list[str] = []
    if str(data.get("dictionary")) != str(board_contract["dicionario"]):
        divergencias.append(
            f"dicionario {data.get('dictionary')!r} != {board_contract['dicionario']!r}")
    if int(data.get("columns", -1)) != int(board_contract["squares_x"]):
        divergencias.append(
            f"columns {data.get('columns')} != squares_x {board_contract['squares_x']}")
    if int(data.get("rows", -1)) != int(board_contract["squares_y"]):
        divergencias.append(
            f"rows {data.get('rows')} != squares_y {board_contract['squares_y']}")
    if bool(data.get("legacy_pattern", False)) != bool(board_contract["legacy_pattern"]):
        divergencias.append("legacy_pattern divergente")

    # square_size_override_cm e a fonte de escala real usada pelo Caliscope.
    square_cm = data.get("square_size_override_cm")
    if square_cm is not None:
        medido_cm = float(board_contract["square_mm_medido"]) / 10.0
        if abs(float(square_cm) - medido_cm) > 1e-6:
            divergencias.append(
                f"square_size_override_cm {square_cm} != medido {medido_cm}")

    if divergencias:
        raise CaliscopeImportError(
            "tabuleiro do Caliscope diverge do tabuleiro fisico do pose: "
            + "; ".join(divergencias)
        )

    return {
        "dictionary": data.get("dictionary"),
        "columns": int(data["columns"]),
        "rows": int(data["rows"]),
        "square_size_cm": float(square_cm) if square_cm is not None else None,
        "aruco_scale": _finite(data.get("aruco_scale", 0.0), field="aruco_scale"),
        "legacy_pattern": bool(data.get("legacy_pattern", False)),
        "units": data.get("units"),
    }


def _load_gate_controls(path: Path, camera_key: str) -> dict[str, Any]:
    """Le o readback real de foco/exposicao do gate de hardware aprovado.

    Foco muda a geometria: um K medido com foco 243 nao descreve a mesma camera
    com foco 300. O valor viaja junto com o perfil justamente para que o
    validador possa reprovar a transferencia quando ele nao bater.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CaliscopeImportError(f"gate report ilegivel: {exc}") from exc

    camera = (data.get("cameras") or {}).get(camera_key)
    if not isinstance(camera, dict):
        raise CaliscopeImportError(f"gate report sem a camera {camera_key!r}")

    controls = (camera.get("source_diagnostics") or {}).get("controls") or {}
    binding = camera.get("binding") or {}
    mode = camera.get("effective_mode") or {}

    final = (controls.get("override") or {}).get("final") or {}
    baseline = controls.get("baseline") or {}
    observavel = controls.get("baseline_observability") or {}

    def _num(fonte: Mapping[str, Any], nome: str) -> float | None:
        try:
            return float(fonte[nome])
        except (KeyError, TypeError, ValueError):
            return None

    # Todo valor de foco que o gate chegou a observar, em qualquer etapa.
    # Se esse conjunto tem mais de um valor, o foco NAO estava travado — e
    # foco solto e a forma mais comum de um intrinseco importado ficar errado
    # sem que nada no arquivo denuncie. Fica registrado.
    focos: list[float] = []
    for fonte in (baseline, final, (controls.get("restore") or {}).get("final") or {}):
        valor = _num(fonte, "focus")
        if valor is not None:
            focos.append(valor)
    for passo in (controls.get("override") or {}).get("steps") or []:
        valor = _num(passo.get("readback") or {}, "focus")
        if valor is not None:
            focos.append(valor)

    autofocus = _num(final, "autofocus")
    focus_travado = len(set(focos)) <= 1

    return {
        "binding": {
            "stable_id": binding.get("stable_id"),
            "friendly_name": binding.get("friendly_name"),
            "binding_method": binding.get("binding_method"),
        },
        "mode": {
            "width": mode.get("width"),
            "height": mode.get("height"),
            "fps": mode.get("fps"),
            "codec": mode.get("codec"),
            "backend": mode.get("backend"),
        },
        "controls": {
            "focus": {
                "value": _num(final, "focus"),
                "observavel": bool(observavel.get("focus", False)),
                "policy": "gate_readback",
                "travado_durante_o_gate": focus_travado,
                "valores_observados": sorted(set(focos)),
                "geometria": "foco altera K; divergencia invalida a transferencia",
            },
            "autofocus": {
                "value": autofocus,
                "observavel": bool(observavel.get("autofocus", False)),
                "geometria": "autofoco ligado faz K variar com a distancia da cena",
            },
            "exposure": {
                "value": _num(final, "exposure"),
                "observavel": bool(observavel.get("exposure", False)),
                "policy": "gate_readback",
                "geometria": "exposicao nao altera K; so brilho e ruido",
            },
        },
        "alertas": _alertas_de_foco(focos, autofocus, focus_travado),
        "gate_passed": bool(camera.get("gate", {}).get("passed", False)),
        "generated_at_utc": data.get("generated_at_utc"),
    }


def _alertas_de_foco(
    focos: list[float], autofocus: float | None, travado: bool
) -> list[str]:
    """Alertas que viajam com o perfil em vez de morrer no console."""
    alertas: list[str] = []
    if not travado and focos:
        alertas.append(
            f"foco variou durante o gate: {sorted(set(focos))}. "
            "Intrinseco so vale para um foco; a transferencia precisa ser medida, "
            "nao presumida."
        )
    if autofocus is not None and autofocus != 0.0:
        alertas.append(
            f"autofocus={autofocus} no readback final (0 = manual). Com autofoco "
            "ativo, fx e fy mudam conforme a distancia da cena."
        )
    return alertas


# --------------------------------------------------------------------------
# Envelope importado
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportedIntrinsics:
    document: dict[str, Any]

    @property
    def import_id(self) -> str:
        return self.document["import_id"]

    @property
    def content_sha256(self) -> str:
        return self.document["integrity"]["content_sha256"]

    @property
    def profile(self) -> dict[str, Any]:
        return self.document["profile"]

    @property
    def passed(self) -> bool:
        return bool(self.document["metrics"]["passed"])

    def save(self, destination: Path, *, overwrite: bool = False) -> Path | None:
        destination = Path(destination)
        backup: Path | None = None
        if destination.exists():
            if not overwrite:
                raise CaliscopeImportError(
                    f"{destination} ja existe; use --overwrite para substituir"
                )
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = destination.with_suffix(destination.suffix + f".{stamp}.bak")
            backup.write_bytes(destination.read_bytes())
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.document, indent=2, ensure_ascii=False, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        return backup

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ImportedIntrinsics":
        schema = raw.get("schema", {})
        if (schema.get("name"), schema.get("version")) != (IMPORT_SCHEMA, SCHEMA_VERSION):
            raise CaliscopeImportError(
                f"schema {schema!r} nao e {IMPORT_SCHEMA} v{SCHEMA_VERSION}. "
                "Documentos de outra versao sao recusados sem conversao automatica."
            )
        _verify_seal(raw, id_field="import_id")
        return cls(document=dict(raw))


def importar_intrinsecos(
    config_path: Path,
    *,
    verificar_videos: bool = False,
) -> ImportedIntrinsics:
    """Importa os intrinsecos de uma camera a partir de um capture_volume Caliscope.

    Todos os hashes declarados na config sao RECALCULADOS. Divergencia e falha
    dura: trocar um artefato de origem tem que invalidar a importacao inteira,
    senao o selo nao significa nada.
    """
    config_path = Path(config_path)
    base = config_path.parent

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CaliscopeImportError(f"config de importacao ilegivel: {exc}") from exc

    schema = config.get("schema", {})
    if (schema.get("name"), schema.get("version")) != (IMPORT_CONFIG_SCHEMA, SCHEMA_VERSION):
        raise CaliscopeImportError(
            f"config precisa declarar schema {IMPORT_CONFIG_SCHEMA} v{SCHEMA_VERSION}"
        )

    camera_key = str(config.get("camera_key") or "").strip()
    if not camera_key:
        raise CaliscopeImportError("config sem camera_key")
    cam_id = int(config["cam_id"])
    rotation_degrees = int(config.get("rotation_degrees", 0))

    # -- manifesto: recalcula todo hash declarado -------------------------
    artefatos = config.get("artefatos")
    if not isinstance(artefatos, dict) or not artefatos:
        raise CaliscopeImportError("config sem bloco 'artefatos'")

    manifest: dict[str, dict[str, Any]] = {}
    caminhos: dict[str, Path] = {}
    for label, entry in sorted(artefatos.items()):
        path = (base / str(entry["path"])).resolve()
        declarado = _require_sha256(entry["sha256"], field=f"artefatos.{label}.sha256")
        atual, size = _sha256_file(path, label=label)
        if atual != declarado:
            raise CaliscopeImportError(
                f"artefato {label} nao confere com o hash declarado.\n"
                f"  arquivo   : {path}\n"
                f"  declarado : {declarado}\n"
                f"  recalculado: {atual}\n"
                "Reimporte a partir da origem; nao atualize o hash a mao."
            )
        manifest[label] = {"path": str(path), "sha256": atual, "size_bytes": size}
        caminhos[label] = path

    faltando = {
        "camera_array", "intrinsic_report", "charuco_toml", "board_contract",
    } - set(caminhos)
    if faltando:
        raise CaliscopeImportError(
            "artefatos obrigatorios ausentes: " + ", ".join(sorted(faltando))
        )

    # -- aquisicao: eixo independente do runtime --------------------------
    aquisicao_cfg = config.get("aquisicao")
    if not isinstance(aquisicao_cfg, dict):
        raise CaliscopeImportError(
            "config sem bloco 'aquisicao'. Declarar a exposicao usada na gravacao "
            "e obrigatorio: sem ela o documento teria de adivinhar."
        )
    videos: dict[str, Any] = {}
    for label, entry in sorted((aquisicao_cfg.get("videos") or {}).items()):
        declarado = _require_sha256(entry["sha256"], field=f"aquisicao.videos.{label}")
        registro = {
            "path": str(entry["path"]),
            "sha256": declarado,
            "verificado": False,
        }
        if verificar_videos or entry.get("verificar"):
            atual, size = _sha256_file(Path(entry["path"]), label=f"video_{label}")
            if atual != declarado:
                raise CaliscopeImportError(
                    f"video de aquisicao {label} nao confere com o hash declarado"
                )
            registro["verificado"] = True
            registro["size_bytes"] = size
        videos[label] = registro

    aquisicao = {
        "kind": "caliscope_geometric_capture",
        "runtime_binding": "none",
        "exposure": _finite(aquisicao_cfg["exposure"], field="aquisicao.exposure"),
        "videos": videos,
        "assurance": (
            "exposicao declarada pelo operador para a captura geometrica; nao e "
            "readback de gate e nao autoriza runtime"
        ),
    }

    # -- leitura dos artefatos --------------------------------------------
    board_contract = json.loads(caminhos["board_contract"].read_text(encoding="utf-8"))
    intrinsics = _load_camera_array(caminhos["camera_array"], cam_id)
    report = _load_intrinsic_report(caminhos["intrinsic_report"])
    charuco = _load_charuco(caminhos["charuco_toml"], board_contract)

    if intrinsics["rotation_count"] * 90 != rotation_degrees:
        raise CaliscopeImportError(
            f"rotation_degrees={rotation_degrees} nao corresponde a "
            f"rotation_count={intrinsics['rotation_count']} do camera_array.toml"
        )

    gate = None
    if "gate_report" in caminhos:
        gate = _load_gate_controls(caminhos["gate_report"], camera_key)
        modo = gate["mode"]
        if modo.get("width") and [modo["width"], modo["height"]] != intrinsics["image_size"]:
            raise CaliscopeImportError(
                f"resolucao do gate {modo['width']}x{modo['height']} diverge da "
                f"resolucao calibrada {intrinsics['image_size']}. Intrinseco vale "
                "para um unico modo; nao ha reescala implicita."
            )

    # -- criterios ---------------------------------------------------------
    veredicto = {
        "rmse_px_max": {
            "aprovado": report["rmse"] <= INTRINSIC_CRITERIA["rmse_px_max"],
            "medido": f"{report['rmse']:.4f} <= {INTRINSIC_CRITERIA['rmse_px_max']}",
        },
        "frames_used_min": {
            "aprovado": report["frames_used"] >= INTRINSIC_CRITERIA["frames_used_min"],
            "medido": f"{report['frames_used']} >= {INTRINSIC_CRITERIA['frames_used_min']}",
        },
        "coverage_fraction_min": {
            "aprovado": report["coverage_fraction"] >= INTRINSIC_CRITERIA["coverage_fraction_min"],
            "medido": f"{report['coverage_fraction']} >= {INTRINSIC_CRITERIA['coverage_fraction_min']}",
        },
        "edge_coverage_fraction_min": {
            "aprovado": report["edge_coverage_fraction"] >= INTRINSIC_CRITERIA["edge_coverage_fraction_min"],
            "medido": f"{report['edge_coverage_fraction']} >= {INTRINSIC_CRITERIA['edge_coverage_fraction_min']}",
        },
        "corner_coverage_fraction_min": {
            "aprovado": report["corner_coverage_fraction"] >= INTRINSIC_CRITERIA["corner_coverage_fraction_min"],
            "medido": f"{report['corner_coverage_fraction']} >= {INTRINSIC_CRITERIA['corner_coverage_fraction_min']}",
        },
        "orientation_sufficient": {
            "aprovado": bool(report["orientation_sufficient"]),
            "medido": f"orientation_count={report['orientation_count']}",
        },
    }
    passed = all(item["aprovado"] for item in veredicto.values())

    # -- documento selado ---------------------------------------------------
    source_identity = _sha256_json(
        {label: entry["sha256"] for label, entry in sorted(manifest.items())}
    )

    profile = {
        "schema": {"name": PROFILE_SCHEMA, "version": SCHEMA_VERSION},
        "camera": {
            "key": camera_key,
            "binding": (gate or {}).get("binding"),
            "mode": (gate or {}).get("mode"),
            "rotation_degrees": rotation_degrees,
            "controls": (gate or {}).get("controls"),
            "acquisition": aquisicao,
        },
        "charuco": {
            "caliscope": charuco,
            "contract": board_contract,
            "contract_sha256": manifest["board_contract"]["sha256"],
        },
        "intrinsics": {
            "image_size": intrinsics["image_size"],
            "K": intrinsics["K"],
            "distortion_model": intrinsics["distortion_model"],
            "distortion_coefficients": intrinsics["distortion_coefficients"],
            "valido_somente_para": (
                f"camera {camera_key} em {intrinsics['image_size'][0]}x"
                f"{intrinsics['image_size'][1]}, com o mesmo foco e o mesmo campo "
                "de visao da aquisicao. Trocar resolucao, foco ou FOV invalida "
                "fx, fy, cx, cy — nao existe reescala implicita."
            ),
        },
        "external_quality": {
            "source": "caliscope.intrinsic_report",
            "criteria": dict(INTRINSIC_CRITERIA),
            "metrics": report,
            "bundle_error_px": intrinsics["bundle_error_px"],
            "veredicto": veredicto,
            "passed": passed,
        },
        "transferencia": {
            "status": str(
                (config.get("origem") or {}).get("transferencia_status")
                or "nao_validada"
            ),
            "motivo": str(
                (config.get("origem") or {}).get("transferencia_motivo")
                or (
                    "K medido em outro projeto. Reaproveitar e hipotese, nao dado. "
                    "Rode validar_transferencia.py na bancada com K congelado."
                )
            ),
            "evidencia": (config.get("origem") or {}).get("transferencia_evidencia"),
        },
        "external_boundary": {
            "kind": "caliscope_intrinsic_import",
            "internal_validation_evidence_present": False,
            "internal_methodology_claimed": False,
            "checksum_assurance": CHECKSUM_ASSURANCE,
        },
    }

    identity = {
        "schema": {"name": IMPORT_SCHEMA, "version": SCHEMA_VERSION},
        "source": {
            "provider": {
                "name": "Caliscope",
                "version": str(config.get("caliscope_version", "desconhecida")),
            },
            "origem": config.get("origem", {}),
            "source_units": "meters",
            "file_manifest": manifest,
            "source_identity_sha256": source_identity,
        },
        "camera_key": camera_key,
        "cam_id": cam_id,
        "profile": profile,
        "metrics": {"intrinsic": report, "criteria": INTRINSIC_CRITERIA, "passed": passed},
        "gate": gate,
        "imported_at": _now(),
    }
    document = _seal(identity, id_field="import_id")

    if not passed:
        reprovados = [k for k, v in veredicto.items() if not v["aprovado"]]
        raise CaliscopeImportError(
            "importacao reprovada nos criterios pre-registrados: "
            + ", ".join(reprovados)
            + ". Recapture no Caliscope; nao relaxe o numero."
        )

    return ImportedIntrinsics(document=document)


# --------------------------------------------------------------------------
# Ativacao
# --------------------------------------------------------------------------


def ativar(
    import_document: Path,
    destino: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Promove um documento importado a perfil ativo do runtime.

    A ativacao nao cria evidencia de validacao interna e nao aprova a
    transferencia: ela apenas carimba qual documento o runtime deve ler.
    """
    raw = json.loads(Path(import_document).read_text(encoding="utf-8"))
    imported = ImportedIntrinsics.from_dict(raw)
    if not imported.passed:
        raise CaliscopeImportError("documento reprovado nao pode ser ativado")

    identity = {
        "schema": {"name": ACTIVE_PROFILE_SCHEMA, "version": SCHEMA_VERSION},
        "camera_key": imported.document["camera_key"],
        "import_document": imported.document,
        "activation_receipt": {
            "import_id": imported.import_id,
            "import_content_sha256": imported.content_sha256,
            "approved": True,
            "authorization_kind": "external_caliscope_import",
        },
        "activated_at": _now(),
        "assurance": CHECKSUM_ASSURANCE,
    }
    active = _seal(identity, id_field="activation_id")

    destino = Path(destino)
    backup: Path | None = None
    if destino.exists():
        if not overwrite:
            raise CaliscopeImportError(
                f"{destino} ja existe; use --overwrite para substituir"
            )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = destino.with_suffix(destino.suffix + f".{stamp}.bak")
        backup.write_bytes(destino.read_bytes())
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(active, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    return {
        "destino": str(destino),
        "backup": str(backup) if backup else None,
        "activation_id": active["activation_id"],
        "import_id": imported.import_id,
        "transferencia_status": imported.profile["transferencia"]["status"],
    }


def carregar_perfil_ativo(path: Path, *, exigir_transferencia: bool = True) -> dict[str, Any]:
    """Le um perfil ativo, verifica o selo e devolve K/dist prontos para uso.

    Com `exigir_transferencia=True` (padrao) recusa perfil cuja transferencia
    ainda nao foi validada na bancada do pose. Esse e o ponto onde a hipotese
    para de passar por dado.
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    schema = raw.get("schema", {})
    if (schema.get("name"), schema.get("version")) != (ACTIVE_PROFILE_SCHEMA, SCHEMA_VERSION):
        raise CaliscopeImportError(f"{path} nao e um perfil ativo v{SCHEMA_VERSION}")
    _verify_seal(raw, id_field="activation_id")

    imported = ImportedIntrinsics.from_dict(raw["import_document"])
    if raw["activation_receipt"]["import_content_sha256"] != imported.content_sha256:
        raise CaliscopeImportError("recibo de ativacao nao casa com o documento importado")

    profile = imported.profile
    transferencia = profile["transferencia"]
    if exigir_transferencia and transferencia["status"] != "validada":
        raise CaliscopeImportError(
            f"transferencia {transferencia['status']!r}: {transferencia['motivo']}"
        )

    return {
        "camera_key": raw["camera_key"],
        "image_size": profile["intrinsics"]["image_size"],
        "K": profile["intrinsics"]["K"],
        "dist": profile["intrinsics"]["distortion_coefficients"],
        "focus_esperado": ((profile["camera"].get("controls") or {}).get("focus") or {}).get("value"),
        "transferencia": transferencia,
        "import_id": imported.import_id,
        "activation_id": raw["activation_id"],
    }


def registrar_transferencia(
    perfil_ativo: Path,
    evidencia: Mapping[str, Any],
) -> dict[str, Any]:
    """Grava o resultado do gate de transferencia dentro do perfil ativo.

    Reserla os dois niveis do documento (import e ativacao), de modo que o
    perfil validado tenha um digest diferente do nao validado — dois arquivos
    com historia diferente nunca colidem.
    """
    perfil_ativo = Path(perfil_ativo)
    raw = json.loads(perfil_ativo.read_text(encoding="utf-8"))
    _verify_seal(raw, id_field="activation_id")

    inner = raw["import_document"]
    _verify_seal(inner, id_field="import_id")

    aprovado = bool(evidencia["aprovado"])
    inner["profile"]["transferencia"] = {
        "status": "validada" if aprovado else "reprovada",
        "motivo": (
            "reprojecao medida na bancada do pose com K congelado"
            if aprovado
            else "reprojecao medida reprovou os criterios pre-registrados"
        ),
        "evidencia": dict(evidencia),
    }

    inner_identity = {k: v for k, v in inner.items() if k not in ("import_id", "integrity")}
    resealed_inner = _seal(inner_identity, id_field="import_id")

    outer_identity = {
        k: v for k, v in raw.items() if k not in ("activation_id", "integrity")
    }
    outer_identity["import_document"] = resealed_inner
    outer_identity["activation_receipt"] = {
        **raw["activation_receipt"],
        "import_id": resealed_inner["import_id"],
        "import_content_sha256": resealed_inner["integrity"]["content_sha256"],
    }
    outer_identity["activated_at"] = _now()
    resealed = _seal(outer_identity, id_field="activation_id")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = perfil_ativo.with_suffix(perfil_ativo.suffix + f".{stamp}.bak")
    backup.write_bytes(perfil_ativo.read_bytes())
    perfil_ativo.write_text(
        json.dumps(resealed, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    return {
        "perfil": str(perfil_ativo),
        "backup": str(backup),
        "status": resealed_inner["profile"]["transferencia"]["status"],
        "activation_id": resealed["activation_id"],
        "import_id": resealed_inner["import_id"],
    }
