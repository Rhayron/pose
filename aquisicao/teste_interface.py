"""Testes sem câmera das regras puras usadas pela interface de aquisição."""

from __future__ import annotations

import sys
import tkinter as tk
import types
import unittest
from importlib.util import find_spec
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

# As regras abaixo não usam OpenCV. O stub permite exercitá-las também num
# ambiente leve de CI; a matriz de aquisição continua responsável por OpenCV.
if find_spec("cv2") is None:
    cv2_stub = types.ModuleType("cv2")
    cv2_stub.__getattr__ = lambda _nome: 0  # type: ignore[attr-defined]
    sys.modules["cv2"] = cv2_stub

from gravar import (  # noqa: E402
    App,
    EstadoApp,
    apresentar_estado,
    parser,
    ponto_dentro_area,
    validar_roi,
)
from sessao import resumir_pre_roll  # noqa: E402


class TesteFuncoesPurasInterface(unittest.TestCase):
    def test_smoke_tk_inicial(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk indisponível: {exc}")
        root.withdraw()
        try:
            app = App(root, parser().parse_args([]))
            self.assertEqual(app.estado_atual, EstadoApp.OCIOSO)
            self.assertIsInstance(app.preview, tk.Canvas)
            self.assertEqual(int(app.preview.cget("width")), 960)
            self.assertEqual(int(app.preview.cget("height")), 540)
            self.assertEqual(app.progresso.winfo_manager(), "")
            app._definir_estado(EstadoApp.SALVANDO)
            self.assertEqual(app.progresso.winfo_manager(), "grid")
            app._definir_estado(EstadoApp.OCIOSO)
            self.assertEqual(app.progresso.winfo_manager(), "")
        finally:
            root.destroy()

    def test_todo_estado_tem_titulo_e_proxima_acao(self) -> None:
        for estado in EstadoApp:
            titulo, proxima = apresentar_estado(estado)
            self.assertTrue(titulo)
            self.assertTrue(proxima.startswith(("Próxima", "Aguarde", "Deixe", "Clique", "Ao", "A sessão", "Leia")))

    def test_roi_respeita_3840x2160(self) -> None:
        self.assertIsNone(validar_roi(None))
        self.assertIsNone(validar_roi((0, 0, 3840, 2160)))
        self.assertIsNone(validar_roi((1700, 40, 160, 120)))
        self.assertIsNotNone(validar_roi((-1, 0, 10, 10)))
        self.assertIsNotNone(validar_roi((0, 0, 0, 10)))
        self.assertIsNotNone(validar_roi((3800, 2100, 50, 80)))

    def test_clique_na_borda_da_janela(self) -> None:
        area = (100, 200, 300, 150)
        self.assertTrue(ponto_dentro_area(100, 200, area))
        self.assertTrue(ponto_dentro_area(399, 349, area))
        self.assertFalse(ponto_dentro_area(400, 349, area))
        self.assertFalse(ponto_dentro_area(99, 200, area))

    def test_pre_roll_e_medido_no_video(self) -> None:
        quadros = [
            {"i": 0, "indice_fonte": 10, "monotonic_ns": 1_000_000_000},
            {"i": 1, "indice_fonte": 11, "monotonic_ns": 1_020_000_000},
            {"i": 2, "indice_fonte": 12, "monotonic_ns": 1_040_000_000},
        ]
        resumo = resumir_pre_roll(quadros, {"monotonic_ns": 1_035_000_000})
        self.assertTrue(resumo["presente"])
        self.assertEqual(resumo["n_quadros_antes_do_marcador"], 2)
        self.assertEqual(resumo["duracao_ms"], 35.0)


if __name__ == "__main__":
    unittest.main()
