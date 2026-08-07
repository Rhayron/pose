"""CLI de importacao de intrinsecos Caliscope para o projeto pose.

    python caliscope_cli.py importar   --config caliscope-import.json --output rig/caliscope-import.json
    python caliscope_cli.py inspecionar rig/caliscope-import.json
    python caliscope_cli.py ativar      rig/caliscope-import.json --destino perfis_ativos/s600.json

Toda saida e um JSON unico em stdout; codigo 0 aprova, 2 reprova. Isso mantem
o comando utilizavel dentro de um gate mecanico sem parsing de texto livre.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from caliscope_import import (
    ACTIVE_PROFILE_SCHEMA,
    IMPORT_SCHEMA,
    CaliscopeImportError,
    ImportedIntrinsics,
    ativar,
    importar_intrinsecos,
)

RAIZ = Path(__file__).resolve().parent


def _caminho(valor: str) -> Path:
    path = Path(valor)
    return path if path.is_absolute() else (RAIZ / path)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__,
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = root.add_subparsers(dest="comando", required=True)

    imp = sub.add_parser("importar", help="le o capture_volume e sela o documento")
    imp.add_argument("--config", default="caliscope-import.json")
    imp.add_argument("--output", default="rig/caliscope-import.json")
    imp.add_argument("--verificar-videos", action="store_true",
                     help="exige os MP4 de aquisicao em disco e reconfere o hash")
    imp.add_argument("--overwrite", action="store_true")

    ins = sub.add_parser("inspecionar", help="valida o selo e resume o documento")
    ins.add_argument("documento")

    act = sub.add_parser("ativar", help="promove o documento a perfil ativo")
    act.add_argument("documento")
    act.add_argument("--destino", default="perfis_ativos/s600.json")
    act.add_argument("--overwrite", action="store_true")

    return root


def comando_importar(args: argparse.Namespace) -> dict:
    imported = importar_intrinsecos(
        _caminho(args.config), verificar_videos=args.verificar_videos
    )
    destino = _caminho(args.output)
    backup = imported.save(destino, overwrite=args.overwrite)
    perfil = imported.profile
    return {
        "ok": True,
        "output": str(destino),
        "backup": str(backup) if backup else None,
        "import_id": imported.import_id,
        "content_sha256": imported.content_sha256,
        "source_identity_sha256": imported.document["source"]["source_identity_sha256"],
        "camera_key": imported.document["camera_key"],
        "image_size": perfil["intrinsics"]["image_size"],
        "rmse_px": perfil["external_quality"]["metrics"]["rmse"],
        "criterios_aprovados": perfil["external_quality"]["passed"],
        "transferencia": perfil["transferencia"]["status"],
        "alertas": (imported.document.get("gate") or {}).get("alertas", []),
        "proximo": (
            f"python caliscope_cli.py ativar {args.output} "
            "--destino perfis_ativos/s600.json"
        ),
    }


def comando_inspecionar(args: argparse.Namespace) -> dict:
    path = _caminho(args.documento)
    raw = json.loads(path.read_text(encoding="utf-8"))
    nome = raw.get("schema", {}).get("name")

    if nome == ACTIVE_PROFILE_SCHEMA:
        from caliscope_import import _verify_seal  # selo externo

        _verify_seal(raw, id_field="activation_id")
        interno = raw["import_document"]
        raw, tipo, extra = interno, "perfil_ativo", {
            "activation_id": raw["activation_id"],
            "activated_at": raw["activated_at"],
        }
    elif nome == IMPORT_SCHEMA:
        tipo, extra = "documento_importado", {}
    else:
        raise CaliscopeImportError(f"schema {nome!r} nao e documento Caliscope do pose")

    imported = ImportedIntrinsics.from_dict(raw)
    perfil = imported.profile
    intr = perfil["intrinsics"]
    K = intr["K"]
    return {
        "ok": True,
        "tipo": tipo,
        **extra,
        "import_id": imported.import_id,
        "content_sha256": imported.content_sha256,
        "camera_key": imported.document["camera_key"],
        "origem": imported.document["source"].get("origem"),
        "image_size": intr["image_size"],
        "fx": K[0][0], "fy": K[1][1], "cx": K[0][2], "cy": K[1][2],
        "distortion_model": intr["distortion_model"],
        "external_quality": {
            "criteria": perfil["external_quality"]["criteria"],
            "metrics": perfil["external_quality"]["metrics"],
            "veredicto": perfil["external_quality"]["veredicto"],
            "passed": perfil["external_quality"]["passed"],
        },
        "transferencia": perfil["transferencia"],
        "controles_do_gate": (perfil["camera"] or {}).get("controls"),
        "alertas": (imported.document.get("gate") or {}).get("alertas", []),
        "external_boundary": perfil["external_boundary"],
        "internal_validation_evidence_present": False,
    }


def comando_ativar(args: argparse.Namespace) -> dict:
    resultado = ativar(
        _caminho(args.documento), _caminho(args.destino), overwrite=args.overwrite
    )
    return {
        "ok": True,
        **resultado,
        "internal_validation_evidence_created": False,
        "proximo": (
            "python validar_transferencia.py --perfil "
            f"{args.destino} --capturas <pasta_com_pngs>"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        payload = {
            "importar": comando_importar,
            "inspecionar": comando_inspecionar,
            "ativar": comando_ativar,
        }[args.comando](args)
        codigo = 0
    except (CaliscopeImportError, OSError, KeyError,
            UnicodeDecodeError, json.JSONDecodeError) as exc:
        payload = {"ok": False, "erro": type(exc).__name__, "mensagem": str(exc)}
        codigo = 2
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False, allow_nan=False)
    sys.stdout.write("\n")
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
