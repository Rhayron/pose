"""App de gravação sincronizada com a aquisição de ultrassom.

Fluxo de uso
------------
1. **PREPARAR** — abre a S600 no modo calibrado, trava foco e exposição, e
   começa a capturar. A partir daqui a câmera está rodando e assentada. Nada é
   gravado ainda.
2. **ARMAR** — o app passa a esperar o próximo clique de mouse, em qualquer
   lugar da tela. Nada é gravado ainda.
3. **Clique no START do software de ultrassom** — esse mesmo clique marca o
   instante na gravação e começa a escrever o vídeo.
4. **PARAR** — encerra, escreve o vídeo e o JSON de metadados.

Por que a câmera não começa no clique
--------------------------------------
Abrir uma webcam USB custa centenas de milissegundos imprevisíveis: negociação
DirectShow, primeiros quadros já velhos no buffer do driver, autoexposição
assentando. Se a captura começasse no clique, toda essa latência entraria no
sincronismo sem ser medida. Capturando desde o PREPARAR, o clique só carimba um
instante em um fluxo já estável — e ainda sobra pré-roll.

O que este esquema vale, e o que não vale
------------------------------------------
O clique é um evento de interface. Entre ele e o primeiro disparo do pulser há
a latência do software proprietário: desconhecida, provavelmente variável, e
impossível de medir daqui. O JSON declara isso como
`sincronismo.qualidade.nivel = "grosseira"`.

Serve para alinhar trechos de trajetória com trechos de aquisição. **Não** serve
para associar uma pose a um A-scan individual. Para isso é preciso um evento
comum físico — uma luz no campo de visão acionada pelo mesmo sinal que dispara
a aquisição. Quando existir, aponte a ROI com `--roi` e o nível sobe para
`"fina"`, com incerteza na casa do milissegundo.

Uso
---
    python gravar.py
    python gravar.py --perfil ../calibracao/perfis_ativos/s600.json
    python gravar.py --roi 1700 40 160 120 --latencia-ms 42.5
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

import cv2
from PIL import Image, ImageTk

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from camera import ErroCamera, FonteCamera, Quadro  # noqa: E402
from sessao import (  # noqa: E402
    Gravacao,
    carregar_perfil_para_sessao,
    novo_id_sessao,
    salvar_metadados,
)

PERFIL_PADRAO = RAIZ.parent / "calibracao" / "perfis_ativos" / "s600.json"
SAIDA_PADRAO = RAIZ / "sessoes"


class EscutaCliqueGlobal:
    """Captura o próximo clique de mouse em qualquer lugar da tela.

    Usa `pynput`. Sem ele o app continua funcionando, mas só com o botão
    interno — o que perde o ponto do exercício, já que o clique precisa ser o
    mesmo que aciona o software de ultrassom.
    """

    def __init__(self) -> None:
        self._listener: Any = None
        self.disponivel = False
        try:
            from pynput import mouse  # noqa: PLC0415

            self._mouse = mouse
            self.disponivel = True
        except ImportError:
            self._mouse = None

    def armar(self, callback: Any) -> None:
        if not self.disponivel:
            raise RuntimeError(
                "pynput não instalado — sem ele não dá para ver o clique que "
                "aciona o outro programa. Instale com: pip install pynput"
            )
        self.cancelar()

        def ao_clicar(x: int, y: int, botao: Any, pressionado: bool) -> bool:
            if not pressionado:
                return True
            # Carimbo tirado no próprio callback, antes de qualquer trabalho de
            # interface, para não somar latência de Tk ao instante do evento.
            callback(time.perf_counter_ns(), {"x": x, "y": y, "botao": str(botao)})
            return False  # encerra o listener

        self._listener = self._mouse.Listener(on_click=ao_clicar)
        self._listener.start()

    def cancelar(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


class App:
    def __init__(self, root: tk.Tk, args: argparse.Namespace) -> None:
        self.root = root
        self.args = args
        self.root.title("Aquisição sincronizada — pose")

        self.fonte: FonteCamera | None = None
        self.gravacao: Gravacao | None = None
        self.perfil: dict[str, Any] | None = None
        self.marcador: dict[str, Any] | None = None
        self.sessao_id: str | None = None
        self.destino_video: Path | None = None
        self.escuta = EscutaCliqueGlobal()
        self._gravando = threading.Event()
        self._ultimo_preview = 0.0

        self.roi = tuple(args.roi) if args.roi else None

        self._montar()
        self._tick()

    # -- interface --------------------------------------------------------

    def _montar(self) -> None:
        painel = ttk.Frame(self.root, padding=10)
        painel.grid(row=0, column=0, sticky="nsew")

        self.preview = tk.Label(painel, background="#111", width=960, height=540)
        self.preview.grid(row=0, column=0, columnspan=4, pady=(0, 10))

        self.btn_preparar = ttk.Button(painel, text="1 · PREPARAR câmera",
                                       command=self.preparar)
        self.btn_preparar.grid(row=1, column=0, sticky="ew", padx=2)

        self.btn_armar = ttk.Button(painel, text="2 · ARMAR (espera clique)",
                                    command=self.armar, state="disabled")
        self.btn_armar.grid(row=1, column=1, sticky="ew", padx=2)

        self.btn_parar = ttk.Button(painel, text="3 · PARAR e salvar",
                                    command=self.parar, state="disabled")
        self.btn_parar.grid(row=1, column=2, sticky="ew", padx=2)

        ttk.Button(painel, text="Cancelar", command=self.cancelar).grid(
            row=1, column=3, sticky="ew", padx=2)

        self.estado = tk.StringVar(value="pronto — clique em PREPARAR")
        ttk.Label(painel, textvariable=self.estado, font=("", 10, "bold")).grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(10, 2))

        self.detalhe = tk.StringVar(value="")
        ttk.Label(painel, textvariable=self.detalhe, foreground="#555").grid(
            row=3, column=0, columnspan=4, sticky="w")

        self.aviso = tk.StringVar(value="")
        ttk.Label(painel, textvariable=self.aviso, foreground="#a60",
                  wraplength=940, justify="left").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))

        ttk.Label(painel, text="Notas da sessão:").grid(
            row=5, column=0, sticky="w", pady=(10, 2))
        self.notas = tk.Text(painel, height=3, width=110)
        self.notas.grid(row=6, column=0, columnspan=4, sticky="ew")

        for coluna in range(4):
            painel.columnconfigure(coluna, weight=1)

    # -- etapas -----------------------------------------------------------

    def preparar(self) -> None:
        try:
            self.perfil = carregar_perfil_para_sessao(
                Path(self.args.perfil) if self.args.perfil else None
            )
        except Exception as exc:  # noqa: BLE001
            self.estado.set(f"erro no perfil: {exc}")
            return

        self.fonte = FonteCamera(
            indice=self.args.camera,
            roi_evento=self.roi,
            focus_esperado=(self.perfil or {}).get("focus_esperado"),
        )
        try:
            modo = self.fonte.abrir()
        except ErroCamera as exc:
            self.estado.set(f"erro: {exc}")
            self.fonte = None
            return

        self.fonte.iniciar()
        self.btn_preparar.config(state="disabled")
        self.btn_armar.config(state="normal")
        self.estado.set(
            f"câmera capturando · {modo['width']}x{modo['height']} @ "
            f"{modo['fps']:.0f} fps — deixe assentar alguns segundos"
        )

        avisos: list[str] = []
        if self.perfil and self.perfil.get("aviso"):
            avisos.append(self.perfil["aviso"])
        # Foco é o que muda a geometria: aparece antes de tudo, e não some da
        # tela até o operador conferir.
        avisos.extend(self.fonte.verificar_foco().get("alertas", []))
        for nome, trava in (self.fonte.travas or {}).items():
            if not trava["obedecido"]:
                avisos.append(
                    f"{nome}: pedido {trava['pedido']}, driver leu {trava['lido']} "
                    f"({'não observável' if not trava['observavel'] else 'não obedeceu'})"
                )
        if self.roi is None:
            avisos.append(
                "sem ROI de evento luminoso: o sincronismo desta sessão será "
                "declarado GROSSEIRO (só o clique)."
            )
        self.aviso.set(" · ".join(avisos))

    def armar(self) -> None:
        if self.fonte is None:
            return
        try:
            self.escuta.armar(self._ao_clique_global)
        except RuntimeError as exc:
            self.estado.set(str(exc))
            return
        self.btn_armar.config(state="disabled")
        self.estado.set(
            "ARMADO — o PRÓXIMO clique em qualquer lugar inicia a gravação. "
            "Clique no START do ultrassom."
        )

    def _ao_clique_global(self, monotonic_ns: int, posicao: dict[str, Any]) -> None:
        """Chamado na thread do listener. Só agenda; não toca em Tk daqui."""
        self.root.after(0, lambda: self._iniciar_gravacao(monotonic_ns, posicao))

    def _iniciar_gravacao(self, monotonic_ns: int, posicao: dict[str, Any]) -> None:
        fonte = self.fonte
        if fonte is None or self._gravando.is_set():
            return

        self.sessao_id = novo_id_sessao()
        pasta = Path(self.args.saida) / self.sessao_id
        self.destino_video = pasta / f"video_{self.sessao_id}.avi"

        self.gravacao = Gravacao(self.destino_video, fonte.modo_efetivo,
                                 codec=self.args.codec)
        try:
            self.gravacao.iniciar()
        except Exception as exc:  # noqa: BLE001
            self.estado.set(f"erro ao abrir o vídeo: {exc}")
            return

        quadro, delta_ms = fonte.quadro_mais_proximo(monotonic_ns)
        self.marcador = {
            "monotonic_ns": monotonic_ns,
            "posicao_tela": posicao,
            "quadro_mais_proximo_na_captura": quadro.indice if quadro else None,
            "delta_para_esse_quadro_ms": (
                round(delta_ms, 3) if quadro else None
            ),
            "significado": (
                "instante em que o sistema operacional entregou o clique. NÃO é "
                "o instante do primeiro disparo do pulser."
            ),
        }

        fonte.assinar(self.gravacao.receber)
        self._gravando.set()

        self.btn_parar.config(state="normal")
        self.estado.set(f"GRAVANDO — sessão {self.sessao_id}")

    def parar(self) -> None:
        if not self._gravando.is_set() or self.fonte is None or self.gravacao is None:
            return
        self._gravando.clear()
        self.fonte.desassinar(self.gravacao.receber)
        self.gravacao.encerrar()
        self.fonte.parar()

        assert self.destino_video is not None and self.sessao_id is not None
        meta = self.destino_video.parent / f"sessao_{self.sessao_id}.json"
        documento = salvar_metadados(
            meta,
            sessao_id=self.sessao_id,
            video=self.destino_video,
            gravacao=self.gravacao,
            fonte=self.fonte,
            perfil=self.perfil,
            marcador=self.marcador,
            latencia_ms=self.args.latencia_ms,
            roi_evento=self.roi,
            notas=self.notas.get("1.0", "end").strip(),
        )

        qualidade = documento["sincronismo"]["qualidade"]
        temporal = documento["camera"]["estatisticas_temporais"]
        self.estado.set(f"salvo em {self.destino_video.parent}")
        self.detalhe.set(
            f"{documento['video']['n_quadros_escritos']} quadros · "
            f"{temporal.get('fps_medido')} fps medidos · "
            f"jitter {temporal.get('jitter_rms_ms')} ms · "
            f"perdidos ~{temporal.get('quadros_perdidos_estimados')} · "
            f"sincronismo: {qualidade['nivel']}"
        )
        self.aviso.set(qualidade["base"])

        self.btn_parar.config(state="disabled")
        self.btn_preparar.config(state="normal")
        self.fonte = None
        self.gravacao = None

    def cancelar(self) -> None:
        self.escuta.cancelar()
        self._gravando.clear()
        if self.gravacao is not None:
            self.gravacao.encerrar()
            self.gravacao = None
        if self.fonte is not None:
            self.fonte.parar()
            self.fonte = None
        self.btn_preparar.config(state="normal")
        self.btn_armar.config(state="disabled")
        self.btn_parar.config(state="disabled")
        self.estado.set("cancelado")

    # -- preview ----------------------------------------------------------

    def _tick(self) -> None:
        fonte = self.fonte
        agora = time.monotonic()
        # Preview a ~15 fps: redesenhar a 60 rouba CPU da captura sem ajudar
        # em nada o operador.
        if fonte is not None and agora - self._ultimo_preview > 0.066:
            self._ultimo_preview = agora
            quadro = fonte.ultimo()
            if quadro is not None:
                self._desenhar(quadro)
                if self._gravando.is_set() and self.gravacao is not None:
                    self.detalhe.set(
                        f"{len(self.gravacao.quadros)} quadros · "
                        f"{fonte.estatisticas.resumo().get('fps_medido')} fps"
                    )
        self.root.after(30, self._tick)

    def _desenhar(self, quadro: Quadro) -> None:
        imagem = cv2.resize(quadro.imagem, (960, 540))
        if self.roi is not None:
            x, y, w, h = self.roi
            escala_x, escala_y = 960 / quadro.imagem.shape[1], 540 / quadro.imagem.shape[0]
            cv2.rectangle(
                imagem,
                (int(x * escala_x), int(y * escala_y)),
                (int((x + w) * escala_x), int((y + h) * escala_y)),
                (0, 255, 255), 2,
            )
            if quadro.brilho_roi is not None:
                cv2.putText(imagem, f"ROI {quadro.brilho_roi:.0f}",
                            (int(x * escala_x), max(int(y * escala_y) - 8, 14)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        if self._gravando.is_set():
            cv2.circle(imagem, (24, 24), 10, (0, 0, 255), -1)

        rgb = cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB)
        foto = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.preview.configure(image=foto)
        self.preview.image = foto  # type: ignore[attr-defined]


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--camera", type=int, default=0, help="índice DirectShow")
    ap.add_argument("--perfil", default=str(PERFIL_PADRAO),
                    help="perfil de calibração ativo (só registrado nos metadados)")
    ap.add_argument("--saida", default=str(SAIDA_PADRAO))
    ap.add_argument("--codec", default="MJPG")
    ap.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "W", "H"),
                    help="região onde a luz de sincronismo aparece no quadro")
    ap.add_argument("--latencia-ms", type=float, default=None,
                    help="latência do pipeline medida com medir_latencia.py")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = tk.Tk()
    app = App(root, args)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.cancelar(), root.destroy()))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
