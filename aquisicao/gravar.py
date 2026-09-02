"""App de gravação sincronizada com a aquisição de ultrassom.

Fluxo de uso
------------
1. **PREPARAR**: abre a S600 no modo calibrado, trava foco e exposição, e
   começa a capturar. A partir daqui a câmera está rodando e assentada. Nada é
   gravado ainda.
2. **ARMAR**: abre o vídeo, assina a fonte e só então passa a esperar o clique
   fora da própria janela. Os quadros deste intervalo são pré-roll real.
3. **Clique no START do software de ultrassom**: esse mesmo clique apenas marca
   o instante no vídeo já aberto e transiciona a interface para GRAVANDO.
4. **PARAR**: encerra, escreve o vídeo e o JSON de metadados.

Por que a câmera não começa no clique
--------------------------------------
Abrir uma webcam USB custa centenas de milissegundos imprevisíveis: negociação
DirectShow, primeiros quadros já velhos no buffer do driver, autoexposição
assentando. Se a captura começasse no clique, toda essa latência entraria no
sincronismo sem ser medida. Capturando desde o PREPARAR, o clique só carimba um
instante em um fluxo já estável, e ainda sobra pré-roll.

O que este esquema vale, e o que não vale
------------------------------------------
O clique é um evento de interface. Entre ele e o primeiro disparo do pulser há
a latência do software proprietário: desconhecida, provavelmente variável, e
impossível de medir daqui. O JSON declara isso como
`sincronismo.qualidade.nivel = "grosseira"`.

Serve para alinhar trechos de trajetória com trechos de aquisição. **Não** serve
para associar uma pose a um A-scan individual. Para isso é preciso um evento
comum físico: uma luz no campo de visão acionada pelo mesmo sinal que dispara
a aquisição. Quando existir, aponte a ROI com `--roi`: o nível só sobe se o
degrau físico for realmente detectado e só chega a `"fina"` quando a transição
puder ser interpolada dentro do quadro.

Uso
---
    python gravar.py
    python gravar.py --perfil ../calibracao/perfis_ativos/s600.json
    python gravar.py --roi 1700 40 160 120 --latencia-ms 42.5
"""

from __future__ import annotations

import argparse
import enum
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
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
    salvar_manifesto_incompleto,
    salvar_metadados,
)

PERFIL_PADRAO = RAIZ.parent / "calibracao" / "perfis_ativos" / "s600.json"
SAIDA_PADRAO = RAIZ / "sessoes"
LARGURA_CAPTURA = 3840
ALTURA_CAPTURA = 2160


class EstadoApp(enum.Enum):
    OCIOSO = "OCIOSO"
    PREPARANDO = "PREPARANDO"
    PRONTO = "PRONTO"
    ARMADO = "ARMADO"
    GRAVANDO = "GRAVANDO"
    SALVANDO = "SALVANDO"
    SALVO = "SALVO"
    ERRO = "ERRO"


def apresentar_estado(estado: EstadoApp) -> tuple[str, str]:
    """Título e próxima ação; função pura usada pela UI e por testes."""
    return {
        EstadoApp.OCIOSO: ("CÂMERA NÃO PREPARADA", "Próxima ação: preparar a câmera."),
        EstadoApp.PREPARANDO: ("PREPARANDO", "Aguarde o primeiro quadro estável."),
        EstadoApp.PRONTO: ("PRONTO", "Deixe o ultrassom visível e então arme."),
        EstadoApp.ARMADO: ("ARMADO", "Clique em START no software de ultrassom."),
        EstadoApp.GRAVANDO: ("GRAVANDO", "Ao terminar, pare para salvar a sessão."),
        EstadoApp.SALVANDO: ("SALVANDO", "Aguarde a confirmação antes de fechar."),
        EstadoApp.SALVO: ("SALVO", "A sessão foi fechada; prepare uma nova se quiser."),
        EstadoApp.ERRO: ("ERRO", "Leia o detalhe e tente preparar novamente."),
    }[estado]


def validar_roi(
    roi: tuple[int, int, int, int] | None,
    largura: int = LARGURA_CAPTURA,
    altura: int = ALTURA_CAPTURA,
) -> str | None:
    """Retorna a causa de uma ROI inválida ou ``None`` quando ela cabe no modo."""
    if roi is None:
        return None
    x, y, w, h = roi
    if x < 0 or y < 0:
        return "X e Y da ROI não podem ser negativos"
    if w <= 0 or h <= 0:
        return "largura e altura da ROI devem ser positivas"
    if x + w > largura or y + h > altura:
        return f"ROI ultrapassa o quadro calibrado de {largura}x{altura}"
    return None


def ponto_dentro_area(x: int, y: int, area: tuple[int, int, int, int]) -> bool:
    """Indica se um clique global pertence à janela do próprio app."""
    esquerda, topo, largura, altura = area
    return esquerda <= x < esquerda + largura and topo <= y < topo + altura


class EscutaCliqueGlobal:
    """Captura o próximo clique de mouse em qualquer lugar da tela.

    Usa `pynput`. Sem ele o app não pode ser armado, porque o marcador precisa
    vir do mesmo clique que aciona o software de ultrassom.
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

    def armar(self, callback: Any, ignorar: Any | None = None) -> None:
        if not self.disponivel:
            raise RuntimeError(
                "pynput não instalado: sem ele não dá para ver o clique que "
                "aciona o outro programa. Instale com: pip install pynput"
            )
        self.cancelar()

        def ao_clicar(x: int, y: int, botao: Any, pressionado: bool) -> bool:
            if not pressionado:
                return True
            if ignorar is not None and ignorar(x, y):
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
        self.root.title("Aquisição sincronizada: pose")
        self.root.geometry("1280x820")
        self.root.minsize(1040, 700)

        self.fonte: FonteCamera | None = None
        self.gravacao: Gravacao | None = None
        self.perfil: dict[str, Any] | None = None
        self.marcador: dict[str, Any] | None = None
        self.sessao_id: str | None = None
        self.destino_video: Path | None = None
        self.escuta = EscutaCliqueGlobal()
        self._gravando = threading.Event()
        self._ultimo_preview = 0.0
        self.estado_atual = EstadoApp.OCIOSO
        self._area_janela = (0, 0, 0, 0)
        self._resultados: queue.Queue[dict[str, Any]] = queue.Queue()
        self._worker_ativo = False
        self._fechar_apos_salvar = False

        self.roi = tuple(args.roi) if args.roi else None
        self._verificacao_af: threading.Thread | None = None

        self._montar()
        self.root.bind("<Escape>", lambda _evento: self.desarmar())
        self._definir_estado(EstadoApp.OCIOSO)
        self._tick()

    # -- interface --------------------------------------------------------

    def _montar(self) -> None:
        painel = ttk.Frame(self.root, padding=10)
        painel.grid(row=0, column=0, sticky="nsew")
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        painel.rowconfigure(1, weight=1)
        painel.columnconfigure(0, weight=3)
        painel.columnconfigure(1, weight=1)

        cabecalho = tk.Frame(painel, background="#263746", padx=14, pady=10)
        cabecalho.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.estado = tk.StringVar()
        self.proxima_acao = tk.StringVar()
        tk.Label(cabecalho, textvariable=self.estado, background="#263746",
                 foreground="white", font=("", 16, "bold")).pack(anchor="w")
        tk.Label(cabecalho, textvariable=self.proxima_acao, background="#263746",
                 foreground="#dce8ef", font=("", 10)).pack(anchor="w")

        quadro_preview = ttk.Frame(painel)
        quadro_preview.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        quadro_preview.rowconfigure(0, weight=1)
        quadro_preview.columnconfigure(0, weight=1)
        # Canvas usa pixels de fato. O tamanho nominal é 960x540 (16:9) e a
        # imagem mantém essa proporção quando a janela é redimensionada.
        self.preview = tk.Canvas(
            quadro_preview, background="#111", width=960, height=540,
            highlightthickness=0,
        )
        self.preview.grid(row=0, column=0, sticky="nsew")
        self._preview_item = self.preview.create_image(0, 0, anchor="nw")

        lateral = ttk.Frame(painel)
        lateral.grid(row=1, column=1, sticky="nsew")
        ttk.Label(lateral, text="PREFLIGHT", font=("", 11, "bold")).pack(anchor="w")
        self.preflight: dict[str, tk.StringVar] = {}
        for chave, titulo in (
            ("integridade", "Integridade da gravação"),
            ("sincronismo", "Sincronismo"),
            ("metrica", "Validade métrica"),
        ):
            caixa = ttk.LabelFrame(lateral, text=titulo, padding=8)
            caixa.pack(fill="x", pady=4)
            variavel = tk.StringVar(value="PENDENTE: prepare a câmera")
            self.preflight[chave] = variavel
            ttk.Label(caixa, textvariable=variavel, wraplength=255,
                      justify="left").pack(anchor="w")

        self.aviso = tk.StringVar(value="")
        ttk.Label(lateral, textvariable=self.aviso, foreground="#9a5b00",
                  wraplength=255, justify="left").pack(anchor="w", pady=(10, 0))

        acoes = ttk.Frame(painel)
        acoes.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        for coluna in range(4):
            acoes.columnconfigure(coluna, weight=1)
        self.btn_preparar = ttk.Button(acoes, text="1 · PREPARAR câmera",
                                       command=self.preparar)
        self.btn_preparar.grid(row=0, column=0, sticky="ew", padx=2)

        self.btn_armar = ttk.Button(acoes, text="2 · ARMAR (espera clique)",
                                    command=self.armar, state="disabled")
        self.btn_armar.grid(row=0, column=1, sticky="ew", padx=2)

        self.btn_parar = ttk.Button(acoes, text="3 · PARAR e salvar",
                                    command=self.parar, state="disabled")
        self.btn_parar.grid(row=0, column=2, sticky="ew", padx=2)

        self.btn_cancelar = ttk.Button(acoes, text="Cancelar", command=self.cancelar)
        self.btn_cancelar.grid(row=0, column=3, sticky="ew", padx=2)

        self.detalhe = tk.StringVar(value="")
        ttk.Label(painel, textvariable=self.detalhe, foreground="#555").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.progresso = ttk.Progressbar(painel, mode="indeterminate")
        self.progresso.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        ttk.Label(painel, text="Notas da sessão:").grid(
            row=5, column=0, sticky="w", pady=(10, 2))
        self.notas = tk.Text(painel, height=3, width=110)
        self.notas.grid(row=6, column=0, columnspan=2, sticky="ew")

    def _definir_estado(self, estado: EstadoApp, detalhe: str | None = None) -> None:
        """Único ponto que sincroniza estado visual e disponibilidade de ações."""
        self.estado_atual = estado
        titulo, proxima = apresentar_estado(estado)
        self.estado.set(titulo)
        self.proxima_acao.set(proxima)
        if detalhe is not None:
            self.detalhe.set(detalhe)

        self.btn_preparar.config(state="disabled")
        self.btn_armar.config(state="disabled", text="2 · ARMAR (espera clique)",
                              command=self.armar)
        self.btn_parar.config(state="disabled")
        self.btn_cancelar.config(state="disabled", text="Cancelar")

        if estado in {EstadoApp.OCIOSO, EstadoApp.SALVO, EstadoApp.ERRO}:
            self.btn_preparar.config(state="normal")
        elif estado == EstadoApp.PREPARANDO:
            self.btn_cancelar.config(state="normal", text="Cancelar preparação")
        elif estado == EstadoApp.PRONTO:
            self.btn_armar.config(state="normal")
            self.btn_cancelar.config(state="normal", text="Cancelar preparação")
        elif estado == EstadoApp.ARMADO:
            self.btn_armar.config(state="normal", text="DESARMAR (Esc)",
                                  command=self.desarmar)
            self.btn_cancelar.config(state="normal", text="Cancelar pré-roll")
        elif estado == EstadoApp.GRAVANDO:
            self.btn_parar.config(state="normal")
            self.btn_cancelar.config(state="normal", text="Interromper…")

        if estado == EstadoApp.SALVANDO:
            self.progresso.grid()
            self.progresso.start(12)
        else:
            self.progresso.stop()
            self.progresso.grid_remove()

    # -- etapas -----------------------------------------------------------

    def preparar(self) -> None:
        erro_roi = validar_roi(self.roi)
        if erro_roi is not None:
            self._definir_estado(EstadoApp.ERRO, f"ROI inválida: {erro_roi}")
            self.preflight["integridade"].set("FALHA: corrija a ROI antes de abrir a câmera")
            return
        self._definir_estado(EstadoApp.PREPARANDO, "Abrindo o modo calibrado 3840x2160…")
        try:
            self.perfil = carregar_perfil_para_sessao(
                Path(self.args.perfil) if self.args.perfil else None
            )
        except Exception as exc:  # noqa: BLE001
            self._definir_estado(EstadoApp.ERRO, f"erro no perfil: {exc}")
            return

        self.fonte = FonteCamera(
            indice=self.args.camera,
            roi_evento=self.roi,
            focus_esperado=(self.perfil or {}).get("focus_esperado"),
        )
        try:
            modo = self.fonte.abrir()
        except ErroCamera as exc:
            self._definir_estado(EstadoApp.ERRO, f"erro: {exc}")
            self.fonte = None
            return

        self.fonte.iniciar()
        self._definir_estado(
            EstadoApp.PREPARANDO,
            f"Modo {modo['width']}x{modo['height']} @ {modo['fps']:.0f} fps aberto; "
            "aguardando o primeiro quadro.",
        )
        self.preflight["integridade"].set("PENDENTE: aguardando o primeiro quadro")
        self.preflight["sincronismo"].set(
            "ATENÇÃO: só clique (grosseiro)" if self.roi is None else
            "PRONTO: evento físico poderá ser medido na ROI; o nível final depende do degrau"
        )
        self.preflight["metrica"].set(
            "NÃO MÉTRICA: transferência/refração e cadeia de referenciais seguem pendentes"
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
        # Um aviso por linha: integridade, sincronismo e validade não se escondem
        # numa frase concatenada.
        self.aviso.set("\n\n".join(f"• {aviso}" for aviso in avisos))

    def _verificar_af_em_worker(self, fonte: FonteCamera) -> None:
        """Prova funcional da trava de foco; só enfileira, sem tocar em Tk."""
        try:
            resultado = fonte.aguardar_estabilidade_foco()
        except Exception as exc:  # noqa: BLE001
            resultado = {"estavel": False, "conclusivo": False, "motivo": repr(exc)}
        # A fonte viaja junto: se o operador cancelou e preparou de novo, o
        # resultado velho não pode ser aplicado à fonte nova.
        self._resultados.put(
            {"tipo": "verificacao_af", "resultado": resultado, "fonte": fonte}
        )

    def _concluir_verificacao_af(self, resultado: dict[str, Any]) -> None:
        """Decide PRONTO ou ERRO com as duas evidências: flag e estabilidade.

        Bloqueia de verdade apenas a instabilidade comprovada — foco variando
        invalida qualquer K único para a sessão, e nada na imagem denuncia.
        Um driver não observável não bloqueia: vira aviso alto, e a sessão
        registra a limitação em vez de fingir garantia.
        """
        fonte = self.fonte
        if fonte is None or self.estado_atual != EstadoApp.PREPARANDO:
            return

        trava = (fonte.travas or {}).get("autofocus", {})
        flag_ok = bool(trava.get("obedecido"))

        if resultado.get("conclusivo") and not resultado.get("estavel"):
            fonte.parar()
            self.fonte = None
            self._verificacao_af = None
            self._definir_estado(
                EstadoApp.ERRO,
                "AUTOFOCO ATIVO: o foco variou durante a verificação "
                f"({resultado.get('valores_observados')}). Um K único não "
                "descreve uma sessão com foco variando. Trave o foco no driver "
                "(utilitário do fabricante) e prepare de novo.",
            )
            self.preflight["metrica"].set(
                "FALHA: foco instável — nenhum quadro desta câmera é utilizável "
                "contra o K selado até a trava funcionar"
            )
            return

        modo = fonte.modo_efetivo
        confirmacao = (
            f"foco estável em {resultado.get('valores_observados')} por "
            f"{resultado.get('n_amostras')} amostras"
            if resultado.get("conclusivo")
            else f"estabilidade não conclusiva: {resultado.get('motivo')}"
        )
        if not flag_ok or not resultado.get("conclusivo"):
            avisos = self.aviso.get()
            extra = (
                f"• trava de foco sem dupla garantia ({confirmacao}; flag "
                f"lida {trava.get('lido')}). A sessão registra o foco por "
                "amostragem; confira o alerta de foco no JSON ao salvar."
            )
            self.aviso.set(f"{avisos}\n\n{extra}" if avisos else extra)

        self._definir_estado(
            EstadoApp.PRONTO,
            f"Câmera estável no modo {modo['width']}x{modo['height']} @ "
            f"{modo['fps']:.0f} fps; {confirmacao}. O vídeo cru começa ao ARMAR.",
        )

    def armar(self) -> None:
        fonte = self.fonte
        if fonte is None or self.estado_atual != EstadoApp.PRONTO:
            return

        # O pré-roll é o próprio início do vídeo, não apenas um buffer de RAM:
        # abre escritor e assina a fonte ANTES de tornar o clique observável.
        self.sessao_id = novo_id_sessao()
        pasta = Path(self.args.saida) / self.sessao_id
        self.destino_video = pasta / f"video_{self.sessao_id}.avi"
        self.gravacao = Gravacao(
            self.destino_video, fonte.modo_efetivo, codec=self.args.codec
        )
        try:
            self.gravacao.iniciar()
            fonte.assinar(self.gravacao.receber)
            self.escuta.armar(self._ao_clique_global, self._clique_no_app)
        except Exception as exc:  # noqa: BLE001
            fonte.desassinar(self.gravacao.receber)
            try:
                self.gravacao.encerrar()
            except Exception:  # noqa: BLE001
                pass
            self._remover_video_armacao()
            self.gravacao = None
            self._definir_estado(EstadoApp.ERRO, f"não foi possível armar: {exc}")
            return

        self._definir_estado(
            EstadoApp.ARMADO,
            "Pré-roll gravando. Cliques nesta janela são ignorados; Esc desarma.",
        )

    def _clique_no_app(self, x: int, y: int) -> bool:
        return ponto_dentro_area(x, y, self._area_janela)

    def _ao_clique_global(self, monotonic_ns: int, posicao: dict[str, Any]) -> None:
        """Chamado no listener: só enfileira, sem tocar em Tk fora da main thread."""
        self._resultados.put({
            "tipo": "clique", "monotonic_ns": monotonic_ns, "posicao": posicao,
        })

    def _iniciar_gravacao(self, monotonic_ns: int, posicao: dict[str, Any]) -> None:
        fonte = self.fonte
        gravacao = self.gravacao
        if fonte is None or gravacao is None or self.estado_atual != EstadoApp.ARMADO:
            return

        quadro, delta_ms = fonte.quadro_mais_proximo(monotonic_ns)
        quadro_video, delta_video_ms = gravacao.quadro_mais_proximo(monotonic_ns)
        self.marcador = {
            "monotonic_ns": monotonic_ns,
            "posicao_tela": posicao,
            "quadro_mais_proximo_na_captura": quadro.indice if quadro else None,
            "delta_para_esse_quadro_ms": (
                round(delta_ms, 3) if quadro else None
            ),
            "quadro_mais_proximo_no_video": (
                quadro_video["i"] if quadro_video else None
            ),
            "delta_para_quadro_no_video_ms": (
                round(delta_video_ms, 3) if quadro_video else None
            ),
            "significado": (
                "instante em que o sistema operacional entregou o clique. NÃO é "
                "o instante do primeiro disparo do pulser."
            ),
        }

        self._gravando.set()
        self._definir_estado(
            EstadoApp.GRAVANDO,
            f"Sessão {self.sessao_id}; o marcador foi registrado sem reabrir o vídeo.",
        )

    def desarmar(self) -> None:
        if self.estado_atual != EstadoApp.ARMADO:
            return
        self.escuta.cancelar()
        if self.fonte is not None and self.gravacao is not None:
            self.fonte.desassinar(self.gravacao.receber)
            try:
                self.gravacao.encerrar()
            except Exception as exc:  # noqa: BLE001
                self._definir_estado(EstadoApp.ERRO, f"erro ao desarmar: {exc}")
                return
        self._remover_video_armacao()
        self.gravacao = None
        self.marcador = None
        self.sessao_id = None
        self.destino_video = None
        self._definir_estado(
            EstadoApp.PRONTO, "Desarmado; o pré-roll temporário foi removido explicitamente."
        )

    def _remover_video_armacao(self) -> None:
        """Remove somente o vídeo exato desta armação e a pasta se estiver vazia."""
        video = self.destino_video
        if video is None:
            return
        try:
            if video.exists():
                video.unlink()
            video.parent.rmdir()
        except OSError:
            # Se houver qualquer outro artefato, preserva a pasta; nunca faz
            # remoção recursiva nem amplia o alvo implicitamente.
            pass

    def parar(self) -> None:
        if (
            self.estado_atual != EstadoApp.GRAVANDO
            or self.fonte is None
            or self.gravacao is None
        ):
            return
        self._gravando.clear()
        self.escuta.cancelar()
        fonte, gravacao = self.fonte, self.gravacao
        fonte.desassinar(gravacao.receber)
        assert self.destino_video is not None and self.sessao_id is not None
        notas = self.notas.get("1.0", "end").strip()
        self._definir_estado(
            EstadoApp.SALVANDO,
            "Fechando vídeo, calculando hash e publicando metadados…",
        )
        self._worker_ativo = True
        threading.Thread(
            target=self._finalizar_em_worker,
            args=(fonte, gravacao, self.destino_video, self.sessao_id, notas),
            name="finalizacao",
            daemon=True,
        ).start()

    def _finalizar_em_worker(
        self,
        fonte: FonteCamera,
        gravacao: Gravacao,
        video: Path,
        sessao_id: str,
        notas: str,
    ) -> None:
        """Finaliza sem tocar em nenhum objeto Tk; o _tick consome o resultado."""
        meta = video.parent / f"sessao_{sessao_id}.json"
        try:
            fonte.parar()
            gravacao.encerrar()
            documento = salvar_metadados(
                meta,
                sessao_id=sessao_id,
                video=video,
                gravacao=gravacao,
                fonte=fonte,
                perfil=self.perfil,
                marcador=self.marcador,
                latencia_ms=self.args.latencia_ms,
                roi_evento=self.roi,
                notas=notas,
            )
            self._resultados.put({"tipo": "salvo", "documento": documento})
        except Exception as exc:  # noqa: BLE001
            manifesto: Path | None = None
            try:
                manifesto = salvar_manifesto_incompleto(
                    meta, sessao_id=sessao_id, video=video, erro=repr(exc)
                )
            except Exception:  # noqa: BLE001
                pass
            self._resultados.put({
                "tipo": "erro_salvar", "erro": repr(exc), "video": video,
                "manifesto": manifesto,
            })

    def cancelar(self) -> None:
        if self.estado_atual == EstadoApp.ARMADO:
            self.desarmar()
            return
        if self.estado_atual == EstadoApp.GRAVANDO:
            resposta = messagebox.askyesnocancel(
                "Interromper gravação?",
                "Sim: parar e salvar agora.\nNão ou Cancelar: continuar gravando.",
                default=messagebox.YES,
            )
            if resposta is True:
                self.parar()
            return
        self.escuta.cancelar()
        if self.fonte is not None:
            self.fonte.parar()
            self.fonte = None
        # O worker de verificação, se existir, morre sozinho; o resultado dele
        # será ignorado porque a fonte não é mais a atual.
        self._definir_estado(EstadoApp.OCIOSO, "Preparação cancelada com segurança.")

    # -- preview ----------------------------------------------------------

    def _tick(self) -> None:
        self._area_janela = (
            self.root.winfo_rootx(), self.root.winfo_rooty(),
            self.root.winfo_width(), self.root.winfo_height(),
        )
        while True:
            try:
                resultado = self._resultados.get_nowait()
            except queue.Empty:
                break
            tipo = resultado["tipo"]
            if tipo == "clique":
                self._iniciar_gravacao(
                    resultado["monotonic_ns"], resultado["posicao"]
                )
            elif tipo == "verificacao_af":
                self._verificacao_af = None
                if resultado["fonte"] is self.fonte:
                    self._concluir_verificacao_af(resultado["resultado"])
            elif tipo == "salvo":
                self._worker_ativo = False
                documento = resultado["documento"]
                qualidade = documento["sincronismo"]["qualidade"]
                temporal = documento["camera"]["estatisticas_temporais"]
                self.fonte = None
                self.gravacao = None
                self._definir_estado(
                    EstadoApp.SALVO, f"Sessão salva em {self.destino_video.parent}"
                )
                self.detalhe.set(
                    f"{documento['video']['n_quadros_escritos']} quadros · "
                    f"{temporal.get('fps_medido')} fps · "
                    f"perdidos ~{temporal.get('quadros_perdidos_estimados')} · "
                    f"sincronismo {qualidade['nivel']}"
                )
                self.aviso.set(f"• {qualidade['base']}")
                if self._fechar_apos_salvar:
                    self.root.destroy()
                    return
            elif tipo == "erro_salvar":
                self._worker_ativo = False
                self.fonte = None
                self.gravacao = None
                apoio = (
                    f" Manifesto: {resultado['manifesto']}."
                    if resultado.get("manifesto") else ""
                )
                self._definir_estado(
                    EstadoApp.ERRO,
                    f"Falha ao salvar: {resultado['erro']}. Vídeo preservado em "
                    f"{resultado['video']}.{apoio}",
                )

        fonte = self.fonte
        agora = time.monotonic()
        if (
            fonte is not None
            and self.estado_atual == EstadoApp.PREPARANDO
            and fonte.ultimo() is not None
            and self._verificacao_af is None
        ):
            # Primeiro quadro chegou. PRONTO só depois da prova funcional da
            # trava de foco: a flag do driver é declaração, foco constante sob
            # observação é evidência. Roda em worker; ~3-4 s com a cena real.
            modo = fonte.modo_efetivo
            self.preflight["integridade"].set(
                f"OK: primeiro quadro {modo['width']}x{modo['height']} recebido"
            )
            self.detalhe.set(
                "Verificando a trava do autofoco (~4 s). Mantenha a cena real "
                "na frente da câmera: autofoco só caça quando tem o que caçar."
            )
            self._verificacao_af = threading.Thread(
                target=self._verificar_af_em_worker, args=(fonte,),
                name="verificacao_af", daemon=True,
            )
            self._verificacao_af.start()
        # Preview a ~15 fps: redesenhar a 60 rouba CPU da captura sem ajudar
        # em nada o operador.
        if fonte is not None and agora - self._ultimo_preview > 0.066:
            self._ultimo_preview = agora
            quadro = fonte.ultimo()
            if quadro is not None:
                self._desenhar(quadro)
                if (
                    self.estado_atual in {EstadoApp.ARMADO, EstadoApp.GRAVANDO}
                    and self.gravacao is not None
                ):
                    telemetria = self.gravacao.telemetria()
                    captura = fonte.estatisticas.resumo()
                    self.detalhe.set(
                        f"{telemetria['duracao_s']:.1f} s · "
                        f"{telemetria['n_quadros_recebidos']} quadros · "
                        f"{captura.get('fps_medido')} fps · fila "
                        f"{telemetria['fila_atual']}/{telemetria['fila_limite']} · "
                        f"descartes {telemetria['descartados_por_fila']}"
                    )
        self.root.after(30, self._tick)

    def _desenhar(self, quadro: Quadro) -> None:
        largura_canvas = max(self.preview.winfo_width(), 1)
        altura_canvas = max(self.preview.winfo_height(), 1)
        escala = min(largura_canvas / 16.0, altura_canvas / 9.0)
        largura = max(int(16 * escala), 1)
        altura = max(int(9 * escala), 1)
        imagem = cv2.resize(quadro.imagem, (largura, altura))
        if self.roi is not None:
            x, y, w, h = self.roi
            escala_x = largura / quadro.imagem.shape[1]
            escala_y = altura / quadro.imagem.shape[0]
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
        x0 = (largura_canvas - largura) // 2
        y0 = (altura_canvas - altura) // 2
        self.preview.coords(self._preview_item, x0, y0)
        self.preview.itemconfigure(self._preview_item, image=foto)
        self.preview.image = foto  # type: ignore[attr-defined]

    def on_close(self) -> None:
        if self.estado_atual == EstadoApp.SALVANDO:
            messagebox.showinfo(
                "Salvamento em andamento",
                "A janela permanecerá aberta até vídeo e metadados serem confirmados.",
            )
            return
        if self.estado_atual == EstadoApp.ARMADO:
            self.desarmar()
            self.cancelar()
            self.root.destroy()
            return
        if self.estado_atual == EstadoApp.GRAVANDO:
            resposta = messagebox.askyesnocancel(
                "Gravação em andamento",
                "Sim: salvar e fechar (recomendado).\n"
                "Não: descartar explicitamente.\nCancelar: continuar gravando.",
                default=messagebox.YES,
            )
            if resposta is True:
                self._fechar_apos_salvar = True
                self.parar()
            elif resposta is False and messagebox.askyesno(
                "Confirmar descarte",
                "Descartar definitivamente o vídeo e o pré-roll desta sessão?",
                default=messagebox.NO,
            ):
                self.escuta.cancelar()
                self._gravando.clear()
                if self.fonte is not None and self.gravacao is not None:
                    self.fonte.desassinar(self.gravacao.receber)
                    self.fonte.parar()
                    self.gravacao.encerrar()
                self._remover_video_armacao()
                self.root.destroy()
            return
        self.cancelar()
        self.root.destroy()


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
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
