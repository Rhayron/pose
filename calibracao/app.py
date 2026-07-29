"""
App de calibração (tkinter) — as quatro etapas em uma janela.

    python app.py

Abas: Tabuleiro -> Captura -> Calibrar -> Validar.

A GUI NÃO reimplementa nada: a captura usa `captura_core.SessaoCaptura` (a
mesma da CLI) e a calibração/validação chamam `calibrar.py` e `validar.py`
como subprocessos. Assim os resultados produzidos aqui e pelo terminal são
o mesmo objeto experimental, e a régua pré-registrada vale para os dois.

Sem dependências novas: tkinter (padrão) + OpenCV. Se Pillow estiver
instalado o preview usa Pillow; senão cai para PPM base64, nativo do Tk.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2

from captura_core import (
    BACKENDS,
    desenhar_estado,
    RESOLUCOES_COMUNS,
    SessaoCaptura,
    abrir_camera,
    desenhar_overlay,
    ler_props,
    procurar_cameras,
    travar_camera,
)
import aceleracao
import roteiro as R
from nucleo import (
    METAS_COBERTURA,
    ConfigTabuleiro,
    agora,
    cobertura_atende,
    construir_board,
    escala_efetiva,
    novo_detector,
)

RAIZ = Path(__file__).resolve().parent
try:
    from PIL import Image, ImageTk
    TEM_PIL = True
except Exception:
    TEM_PIL = False

COR_OK, COR_ERRO, COR_ALERTA = "#0a7a28", "#b00020", "#a86a00"


def para_photo(frame_bgr, largura_max=760):
    """ndarray BGR -> imagem do Tk.

    Com Pillow, caminho direto. Sem Pillow, codifica em PNG e passa em base64:
    o Tk 8.6 aceita PNG no `-data`, mas NÃO aceita PPM (só PPM em arquivo) —
    tentar PPM em base64 resulta em "couldn't recognize image data".
    """
    h, w = frame_bgr.shape[:2]
    if w > largura_max:
        esc = largura_max / w
        frame_bgr = cv2.resize(frame_bgr, (int(w * esc), int(h * esc)), interpolation=cv2.INTER_AREA)
    if TEM_PIL:
        return ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)))
    ok, buf = cv2.imencode(".png", frame_bgr, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    if not ok:
        raise RuntimeError("falha ao codificar o quadro para exibição")
    return tk.PhotoImage(data=base64.b64encode(buf.tobytes()))


class LoopCaptura(threading.Thread):
    """Lê a câmera, monta o preview e avalia SOB DEMANDA. Não toca em widgets.

    Dois níveis de detecção, com custo medido em quadro 4K real:

    * GUIA (`detectar_ao_vivo`): 640 px de lado, 5,8 ms, no máximo ~8 vezes por
      segundo. Só orienta — diz se a pose atual é pequena/média/grande e o
      ângulo de inclinação, para você não capturar às cegas.
    * CLIQUE: quadro cheio, 71,5 ms. É a mesma detecção que `calibrar.py` fará
      no PNG, então aceitar ou recusar aqui coincide com o que vale.

    Detectar o quadro cheio a cada quadro (o que eu fazia antes) custa mais que
    o intervalo entre quadros e trava a janela.

    O preview é reduzido AQUI, na thread: assim a thread da UI nunca manipula
    um array de 4K, que a 20 quadros/s seriam centenas de MB/s só de cópia.
    """

    def __init__(self, cap, sessao, fila, fila_eventos=None, cooldown=0.8,
                 largura_preview=960):
        super().__init__(daemon=True)
        self.cap, self.sessao, self.fila, self.cooldown = cap, sessao, fila, cooldown
        # Mensagens vão em fila PRÓPRIA e ilimitada. Antes viajavam junto do
        # quadro, numa fila de 1 posição: o quadro seguinte sobrescrevia o
        # anterior e a mensagem sumia — inclusive a confirmação de captura.
        self.fila_eventos = fila_eventos if fila_eventos is not None else queue.Queue()
        self.largura_preview = int(largura_preview)
        self.parar = threading.Event()
        self.auto = threading.Event()
        self.detectar_ao_vivo = threading.Event()
        self.pedir_captura = threading.Event()
        self.pedir_desfazer = threading.Event()
        self.pedir_analise = threading.Event()
        self.pedir_varredura_foco = threading.Event()
        self.foco_manual = None       # valor pedido pela UI, aplicado no laço
        self.varredura_resultado = None   # a UI consome e preenche os campos
        self.ultimo_aval = None
        self.ultimo_ms = 0.0
        self.lado_guia = 640          # 5,8 ms em quadro 4K real (medido)
        self.intervalo_guia = 0.12    # no máximo ~8 guias por segundo
        self._ultimo_guia = 0.0
        self.faltando: tuple = ()
        self.cobertura_ok = False
        # roteiro guiado: o laço dispara a captura sozinho quando o passo é
        # atendido por alguns quadros seguidos — tirar o gesto de apertar o
        # botão elimina a principal fonte de borrão de movimento
        self.roteiro: list = []
        self.idx_passo = 0
        self.roteiro_ativo = threading.Event()
        self.estaveis_necessarios = 4
        self._estaveis = 0
        self.faltas_passo: list = []
        # O driver pode ignorar o pedido de travar foco/exposição. Em vez de
        # supor que travou, AMOSTRAMOS as propriedades durante a sessão: se
        # variarem, fica registrado e a calibração é suspeita.
        self.props_observadas: dict[str, list[float]] = {}

    def _amostrar_props(self):
        for nome, pid in (("FOCUS", cv2.CAP_PROP_FOCUS),
                          ("EXPOSURE", cv2.CAP_PROP_EXPOSURE),
                          ("ZOOM", cv2.CAP_PROP_ZOOM)):
            try:
                v = float(self.cap.get(pid))
            except cv2.error:
                continue
            self.props_observadas.setdefault(nome, [])
            if v not in self.props_observadas[nome]:
                self.props_observadas[nome].append(v)

    def resumo_props(self) -> dict:
        saida = {}
        for nome, vals in self.props_observadas.items():
            if not vals or all(v in (-1.0, 0.0) for v in vals) and len(vals) == 1:
                saida[nome] = {"observavel": False, "valores": vals}
            else:
                saida[nome] = {"observavel": True, "valores": sorted(vals),
                               "constante": len(vals) == 1}
        return saida

    def run(self):
        """Nunca morre em silêncio.

        Uma exceção aqui dentro encerrava a thread sem aviso: o preview
        congelava e nenhum botão trazia a câmera de volta, porque não havia
        mais quem lesse a câmera. Agora o erro é reportado pela fila e o laço
        continua — se for persistente, aparece repetido no log.
        """
        ultimo, n, erros = 0.0, 0, 0
        while not self.parar.is_set():
            try:
                ultimo, n = self._passo(ultimo, n)
                erros = 0
            except Exception as e:
                erros += 1
                self._emitir(f"[ERRO na captura] {type(e).__name__}: {e}")
                if erros >= 20:
                    break
                time.sleep(0.2)

    def _emitir(self, texto):
        self.fila_eventos.put(texto)

    def passo_atual(self):
        """Adaptativo: o passo é sempre a meta mais urgente ainda aberta."""
        if not self.roteiro_ativo.is_set():
            return None
        return R.proximo(self.sessao.resumo())

    def _checar_roteiro(self, aval) -> bool:
        """Devolve True quando o passo atual foi atendido e estável."""
        passo = self.passo_atual()
        if passo is None:
            return False
        ok, faltas = R.avaliar(passo, aval)
        self.faltas_passo = faltas
        self._estaveis = self._estaveis + 1 if ok else 0
        return self._estaveis >= self.estaveis_necessarios

    def avancar_passo(self, delta=1, motivo=""):
        """No modo adaptativo não há o que pular: o passo vem do que falta."""
        self._estaveis = 0
        p = self.passo_atual()
        if p is None:
            self._emitir("[roteiro] todas as metas fechadas")
        else:
            self._emitir(f"[roteiro] agora: {p.descricao}{motivo}")

    def _medir_foco(self, valor, esperar=0.35, descartar=3):
        """Aplica um valor de foco e mede a nitidez do alvo já estabilizado."""
        self.cap.set(cv2.CAP_PROP_FOCUS, float(valor))
        time.sleep(esperar)
        for _ in range(descartar):          # descarta quadros do transiente
            self.cap.read()
        ok, f = self.cap.read()
        if not ok:
            return None
        a = self.sessao.avaliar(f, lado_max=self.lado_guia)
        return (a["nitidez"], a["n_cantos"]) if a["cantos"] is not None else (0.0, 0)

    def _varrer_foco(self):
        """Acha o foco por MEDIÇÃO: varre valores e fica no de maior nitidez.

        Grosso e depois fino. A nitidez é medida na região do tabuleiro, então
        o alvo precisa ficar parado, na distância de trabalho, durante a
        varredura toda.
        """
        original = float(self.cap.get(cv2.CAP_PROP_FOCUS))
        self._emitir(f"\n== varredura de foco (atual {original:g}) — "
                     f"segure o tabuleiro parado na distancia de trabalho ==")
        resultados = []
        for v in range(0, 601, 50):
            r = self._medir_foco(v)
            if r is None:
                continue
            resultados.append((v, r[0]))
            self._emitir(f"   foco {v:4d} -> nitidez {r[0]:8.1f}  (cantos {r[1]})")
        if not resultados or max(r[1] for r in resultados) <= 0:
            self.cap.set(cv2.CAP_PROP_FOCUS, original)
            self._emitir("[erro] nenhum foco produziu deteccao. O tabuleiro estava no quadro?")
            return
        melhor = max(resultados, key=lambda t: t[1])[0]
        self._emitir(f"   -- refinando em torno de {melhor}")
        finos = []
        for v in range(max(0, melhor - 50), melhor + 51, 10):
            r = self._medir_foco(v, esperar=0.25)
            if r is None:
                continue
            finos.append((v, r[0]))
            self._emitir(f"   foco {v:4d} -> nitidez {r[0]:8.1f}  (cantos {r[1]})")
        v_bom, nit = max(finos or resultados, key=lambda t: t[1])
        self.cap.set(cv2.CAP_PROP_FOCUS, float(v_bom))
        time.sleep(0.3)
        lido = float(self.cap.get(cv2.CAP_PROP_FOCUS))
        self._emitir(f"[ok] foco = {v_bom} (nitidez {nit:.0f}); lido de volta {lido:g}")
        if abs(lido - v_bom) > 1e-6:
            self._emitir("[!!] o driver nao aceitou o valor — o foco NAO esta sob controle")
        # A UI lê isto e preenche os campos sozinha: reescrever à mão um valor
        # que a varredura acabou de medir é só oportunidade de errar de dígito.
        self.varredura_resultado = {"foco": float(v_bom), "nitidez_pico": float(nit),
                                    "nitidez_min": round(nit / 2)}
        self._emitir(f"[dica] limiar de nitidez sugerido: {nit/2:.0f} (metade do medido aqui)\n")

    def _passo(self, ultimo, n):
        """Um ciclo: lê, avalia se pedido, grava se pedido, publica o preview."""
        if True:
            ok, frame = self.cap.read()
            if not ok:
                self._emitir("falha ao ler quadro da câmera")
                time.sleep(0.05)
                return ultimo, n
            n += 1
            if n % 15 == 1:
                self._amostrar_props()

            if self.foco_manual is not None:
                v = self.foco_manual
                self.foco_manual = None
                r = self._medir_foco(v)
                lido = float(self.cap.get(cv2.CAP_PROP_FOCUS))
                self._emitir(f"foco pedido {v:g} -> lido {lido:g}" +
                             (f", nitidez {r[0]:.0f}" if r else "") +
                             ("" if abs(lido - v) < 1e-6 else "   [!!] driver ignorou"))
            if self.pedir_varredura_foco.is_set():
                self.pedir_varredura_foco.clear()
                self._varrer_foco()

            manual = self.pedir_captura.is_set()
            if manual:
                self.pedir_captura.clear()
            analise = self.pedir_analise.is_set()
            if analise:
                self.pedir_analise.clear()

            # detecta quando alguém precisa do resultado; o guia é limitado
            # por tempo para nunca competir com a leitura da câmera
            aval = None
            sob_demanda = manual or analise
            agora_s = time.time()
            guia = (not sob_demanda and (self.detectar_ao_vivo.is_set() or self.auto.is_set())
                    and agora_s - self._ultimo_guia >= self.intervalo_guia)
            if sob_demanda or guia:
                t0 = time.perf_counter()
                # no clique, quadro CHEIO (lado_max=0): mesma detecção que
                # calibrar.py fará, então aceitar/recusar aqui vale de verdade
                aval = self.sessao.avaliar(frame, lado_max=0 if sob_demanda else self.lado_guia)
                self.ultimo_ms = (time.perf_counter() - t0) * 1000.0
                self.ultimo_aval = aval
                if guia:
                    self._ultimo_guia = agora_s

            if self.roteiro_ativo.is_set() and aval is not None and not sob_demanda:
                manual = self._checar_roteiro(aval) or manual

            if self.pedir_desfazer.is_set():
                self.pedir_desfazer.clear()
                removido = self.sessao.desfazer()
                self._emitir(f"desfeita {removido}" if removido else "nada a desfazer")

            auto_ok = (self.auto.is_set() and aval is not None and aval["capturavel"]
                       and aval["novo_bin"] and (time.time() - ultimo) > self.cooldown)
            if (manual or auto_ok) and aval is not None:
                nome = self.sessao.registrar(frame, aval)
                if nome:
                    ultimo = time.time()
                    self._emitir(f"+ {nome}  cantos={aval['n_cantos']}  "
                                 f"nitidez={aval['nitidez']:.0f}  "
                                 f"tilt={aval['tilt']:.0f}deg  "
                                 f"({aval['classe']['escala']}/{aval['classe']['tilt']})")
                    if self.roteiro_ativo.is_set():
                        self.avancar_passo()
                else:
                    self._emitir(f"RECUSADA: {aval['motivo']}")
            elif analise and aval is not None:
                self._emitir(f"análise (não gravou): {aval['motivo']} | "
                             f"cantos {aval['n_cantos']} | nitidez {aval['nitidez']:.0f}"
                             if aval["cantos"] is not None else
                             "análise (não gravou): sem tabuleiro no quadro")

            esc = min(1.0, self.largura_preview / frame.shape[1])
            prev = (cv2.resize(frame, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA)
                    if esc < 1.0 else frame.copy())
            celulas = {r["celula"] for r in self.sessao.registros}
            mostrado = aval or self.ultimo_aval or {}
            desenhar_overlay(prev, mostrado, celulas, escala=esc)
            passo = self.passo_atual()
            if passo is not None:
                desenhar_estado(prev, mostrado, self.faltando, self.cobertura_ok,
                                passo=(f"VISTA {passo.n}: {passo.descricao}",
                                       self.faltas_passo, self._estaveis,
                                       self.estaveis_necessarios))
            else:
                desenhar_estado(prev, mostrado, self.faltando, self.cobertura_ok)
            snap = {"vis": prev, "aval": aval, "ultimo_aval": self.ultimo_aval,
                    "resumo": self.sessao.resumo(), "celulas": celulas,
                    "ms_det": self.ultimo_ms,
                    "resolucao": (frame.shape[1], frame.shape[0]),
                    "ao_vivo": self.detectar_ao_vivo.is_set()}
            try:
                self.fila.get_nowait()      # descarta o quadro anterior não exibido
            except queue.Empty:
                pass
            try:
                self.fila.put_nowait(snap)
            except queue.Full:
                pass
            return ultimo, n


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Calibração intrínseca — WP1 · Exp. 0")
        self.geometry("1240x820")
        self.minsize(1080, 720)

        self.fila_ui: queue.Queue = queue.Queue()
        self.fila_frames: queue.Queue = queue.Queue(maxsize=1)
        self.cap = None
        self.loop = None
        self.sessao = None
        self.pasta_continuar = None
        self._foto = None
        self._foto_prev = None
        self._foto_val = None

        self.var_tabuleiro = tk.StringVar(value=str(RAIZ / "saida" / "tabuleiro.json"))
        self.var_status = tk.StringVar(value="pronto")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.nb = nb
        self.aba_tabuleiro(nb)
        self.aba_captura(nb)
        self.aba_calibrar(nb)
        self.aba_validar(nb)

        ttk.Separator(self).pack(fill="x")
        ttk.Label(self, textvariable=self.var_status, anchor="w").pack(fill="x", padx=10, pady=4)

        self.bind("<space>", lambda e: self._atalho(self.capturar))
        self.bind("<u>", lambda e: self._atalho(self.desfazer))
        self.bind("<U>", lambda e: self._atalho(self.desfazer))
        self.bind("<a>", lambda e: self._atalho(self.analisar))
        self.bind("<A>", lambda e: self._atalho(self.analisar))
        self.protocol("WM_DELETE_WINDOW", self.fechar)
        self.carregar_contrato()
        if not TEM_PIL:
            self.log(self.log_tabuleiro,
                     "[nota] Pillow não instalado — o preview usa PNG em base64 (funciona,\n"
                     "       porém mais lento). Para acelerar: pip install pillow\n")
        self.after(60, self._bombear)
        self.after(30, self._render)

    # ================= infraestrutura =================
    def status(self, txt):
        self.var_status.set(txt)

    def log(self, widget, txt):
        widget.configure(state="normal")
        widget.insert("end", txt)
        widget.see("end")
        widget.configure(state="disabled")

    def _bombear(self):
        """Executa, na thread da UI, o que as threads de trabalho enfileiraram."""
        while True:
            try:
                fn = self.fila_ui.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as e:  # nunca deixar a UI morrer por causa de um callback
                print("erro em callback da UI:", e)
        self.after(60, self._bombear)

    def _sincronizar_criterios(self):
        """Aplica na sessão o que está nos campos AGORA.

        Antes os critérios só eram lidos ao abrir a câmera: digitar 75 em
        `nitidez mín.` no meio da sessão não tinha efeito algum, e o log
        continuava recusando contra 120.
        """
        if self.sessao is None:
            return
        mudancas = self.sessao.ajustar(self.v_mincantos.get(),
                                       self.v_nitidez.get(),
                                       self.v_maxbin.get())
        for m in mudancas:
            self.log(self.log_captura, f"[criterio] {m}  (registrado em sessao.json)\n")

    def _aplicar_varredura(self):
        """Preenche foco e limiar com o que a varredura mediu."""
        if self.loop is None or self.loop.varredura_resultado is None:
            return
        r = self.loop.varredura_resultado
        self.loop.varredura_resultado = None
        self.v_foco.set(f"{r['foco']:g}")
        self.v_nitidez.set(str(r["nitidez_min"]))
        self.log(self.log_captura,
                 f"[auto] foco {r['foco']:g} e nitidez min {r['nitidez_min']} "
                 f"preenchidos a partir da varredura (pico {r['nitidez_pico']:.0f})\n")

    def _render(self):
        self._aplicar_varredura()
        self._sincronizar_criterios()
        try:
            snap = self.fila_frames.get_nowait()
        except queue.Empty:
            snap = None
        if snap is not None:
            if snap.get("vis") is not None:
                self._mostrar_preview(snap["vis"])
            self._atualizar_cobertura(snap)
        if self.loop is not None:            # drena TODAS as mensagens pendentes
            while True:
                try:
                    self.log(self.log_captura, self.loop.fila_eventos.get_nowait() + "\n")
                except queue.Empty:
                    break
        self.after(30, self._render)

    def _mostrar_preview(self, vis):
        """Desenha o quadro ajustado ao Canvas, sem que o conteúdo altere o layout."""
        c = self.canvas_preview
        cw, ch = c.winfo_width(), c.winfo_height()
        if cw < 20 or ch < 20:
            return
        h, w = vis.shape[:2]
        esc = min(cw / w, ch / h)
        if esc < 1.0:
            vis = cv2.resize(vis, (max(1, int(w * esc)), max(1, int(h * esc))),
                             interpolation=cv2.INTER_AREA)
        self._foto = para_photo(vis, largura_max=10 ** 9)   # já dimensionado acima
        c.delete("all")
        c.create_image(cw // 2, ch // 2, image=self._foto)

    def rodar_script(self, argumentos, log_widget, ao_terminar=None, titulo=""):
        self.status(f"executando {titulo}…")
        self.log(log_widget, f"\n$ python {' '.join(str(a) for a in argumentos)}\n")

        def worker():
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            try:
                p = subprocess.Popen(
                    [sys.executable, "-u", *[str(a) for a in argumentos]], cwd=str(RAIZ),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    encoding="utf-8", errors="replace", env=env)
            except Exception as e:
                # `e` deixa de existir ao sair do except: capturar a mensagem agora
                self.fila_ui.put(lambda msg=str(e): self.log(log_widget, f"[erro ao iniciar] {msg}\n"))
                return
            for linha in p.stdout:
                self.fila_ui.put(lambda l=linha: self.log(log_widget, l))
            p.wait()
            self.fila_ui.put(lambda: self.log(log_widget, f"[código de saída {p.returncode}]\n"))
            self.fila_ui.put(lambda: self.status("pronto"))
            if ao_terminar:
                self.fila_ui.put(lambda: ao_terminar(p.returncode))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def abrir_no_sistema(caminho):
        caminho = str(caminho)
        try:
            if sys.platform.startswith("win"):
                os.startfile(caminho)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", caminho])
            else:
                subprocess.Popen(["xdg-open", caminho])
        except Exception as e:
            messagebox.showerror("Abrir", f"não consegui abrir {caminho}\n{e}")

    # ================= aba 1: tabuleiro =================
    def aba_tabuleiro(self, nb):
        aba = ttk.Frame(nb)
        nb.add(aba, text="1 · Tabuleiro")
        esq = ttk.Frame(aba)
        esq.pack(side="left", fill="y", padx=12, pady=12)
        dir_ = ttk.Frame(aba)
        dir_.pack(side="left", fill="both", expand=True, padx=12, pady=12)

        p = ttk.LabelFrame(esq, text="Parâmetros do tabuleiro")
        p.pack(fill="x")
        self.v_sx = tk.StringVar(value="7")
        self.v_sy = tk.StringVar(value="5")
        self.v_quad = tk.StringVar(value="35")
        self.v_marc = tk.StringVar(value="26")
        self.v_dic = tk.StringVar(value="DICT_4X4_50")
        self.v_pag = tk.StringVar(value="A4-paisagem")
        campos = [("quadrados em X", self.v_sx), ("quadrados em Y", self.v_sy),
                  ("lado do quadrado (mm)", self.v_quad), ("lado do marcador (mm)", self.v_marc)]
        for i, (rot, var) in enumerate(campos):
            ttk.Label(p, text=rot).grid(row=i, column=0, sticky="w", padx=8, pady=3)
            ttk.Entry(p, textvariable=var, width=12).grid(row=i, column=1, padx=8, pady=3)
        ttk.Label(p, text="dicionário").grid(row=4, column=0, sticky="w", padx=8, pady=3)
        ttk.Combobox(p, textvariable=self.v_dic, width=16, values=[
            "DICT_4X4_50", "DICT_4X4_100", "DICT_6X6_100", "DICT_APRILTAG_36h11"
        ]).grid(row=4, column=1, padx=8, pady=3)
        ttk.Label(p, text="página").grid(row=5, column=0, sticky="w", padx=8, pady=3)
        ttk.Combobox(p, textvariable=self.v_pag, width=16, values=[
            "A4-paisagem", "A4-retrato", "A3-paisagem", "A3-retrato", "carta-paisagem"
        ]).grid(row=5, column=1, padx=8, pady=3)
        ttk.Button(p, text="Gerar tabuleiro", command=self.gerar_tabuleiro).grid(
            row=6, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 8))

        e = ttk.LabelFrame(esq, text="Escala métrica (obrigatória)")
        e.pack(fill="x", pady=12)
        ttk.Label(e, text="Imprima o SVG em 100%, meça 5 quadrados com paquímetro,\n"
                          "divida por 5 e escreva aqui. É o único número que dá\n"
                          "escala em mm a todo o projeto.", justify="left").pack(
            anchor="w", padx=8, pady=(6, 4))
        lin = ttk.Frame(e)
        lin.pack(fill="x", padx=8, pady=4)
        self.v_medido = tk.StringVar()
        ttk.Label(lin, text="quadrado medido (mm)").pack(side="left")
        ttk.Entry(lin, textvariable=self.v_medido, width=10).pack(side="left", padx=6)
        ttk.Button(lin, text="Salvar no contrato", command=self.salvar_medida).pack(side="left")
        self.lbl_escala = ttk.Label(e, text="", foreground=COR_ERRO, justify="left")
        self.lbl_escala.pack(anchor="w", padx=8, pady=(2, 8))

        b = ttk.Frame(esq)
        b.pack(fill="x")
        ttk.Button(b, text="Abrir pasta saida/", command=lambda: self.abrir_no_sistema(RAIZ / "saida")).pack(side="left")
        ttk.Button(b, text="Abrir SVG", command=lambda: self.abrir_no_sistema(RAIZ / "saida" / "tabuleiro.svg")).pack(side="left", padx=6)

        ttk.Label(dir_, text="Pré-visualização", font=("", 10, "bold")).pack(anchor="w")
        self.lbl_prev_tab = ttk.Label(dir_, text="(gere o tabuleiro para ver)", anchor="center")
        self.lbl_prev_tab.pack(fill="both", expand=True)
        self.log_tabuleiro = tk.Text(dir_, height=8, state="disabled", wrap="word")
        self.log_tabuleiro.pack(fill="x", pady=(8, 0))

    def gerar_tabuleiro(self):
        args = ["gerar_tabuleiro.py", "--squares", self.v_sx.get(), self.v_sy.get(),
                "--quadrado-mm", self.v_quad.get(), "--marcador-mm", self.v_marc.get(),
                "--dicionario", self.v_dic.get(), "--pagina", self.v_pag.get(),
                "--saida", str(RAIZ / "saida")]
        self.rodar_script(args, self.log_tabuleiro,
                          ao_terminar=lambda rc: self.carregar_contrato(),
                          titulo="gerar_tabuleiro")

    def carregar_contrato(self):
        caminho = Path(self.var_tabuleiro.get())
        png = RAIZ / "saida" / "tabuleiro.png"
        if png.exists():
            img = cv2.imread(str(png))
            if img is not None:
                # uma falha de PRÉ-VISUALIZAÇÃO não pode derrubar o app inteiro
                try:
                    self._foto_prev = para_photo(img, largura_max=560)
                    self.lbl_prev_tab.configure(image=self._foto_prev, text="")
                except Exception as e:
                    self.lbl_prev_tab.configure(text=f"(pré-visualização indisponível: {e})")
        if not caminho.exists():
            self.lbl_escala.configure(text="contrato ainda não existe — gere o tabuleiro",
                                      foreground=COR_ALERTA)
            return
        cfg = json.loads(caminho.read_text(encoding="utf-8"))
        if cfg.get("square_mm_medido") is None:
            self.lbl_escala.configure(
                text=f"nominal {cfg['square_mm_nominal']} mm — NÃO MEDIDO.\n"
                     f"A calibração vai se recusar a rodar até você medir.",
                foreground=COR_ERRO)
        else:
            d = cfg["square_mm_medido"] / cfg["square_mm_nominal"] - 1
            self.lbl_escala.configure(
                text=f"medido {cfg['square_mm_medido']} mm "
                     f"(nominal {cfg['square_mm_nominal']} — desvio de impressão {d*100:+.2f}%)",
                foreground=COR_OK)
            self.v_medido.set(str(cfg["square_mm_medido"]))

    def salvar_medida(self):
        caminho = Path(self.var_tabuleiro.get())
        if not caminho.exists():
            messagebox.showerror("Contrato", "gere o tabuleiro primeiro")
            return
        try:
            valor = float(self.v_medido.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Medida", "valor inválido")
            return
        cfg = json.loads(caminho.read_text(encoding="utf-8"))
        desvio = abs(valor / cfg["square_mm_nominal"] - 1)
        if desvio > 0.1 and not messagebox.askyesno(
                "Confirmar", f"O valor difere {desvio*100:.1f}% do nominal "
                             f"({cfg['square_mm_nominal']} mm). Isso é muito para um erro de\n"
                             f"impressão — confira a unidade. Salvar mesmo assim?"):
            return
        cfg["square_mm_medido"] = valor
        caminho.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        self.log(self.log_tabuleiro, f"[ok] square_mm_medido = {valor} salvo em {caminho}\n")
        self.carregar_contrato()

    # ================= aba 2: captura =================
    def aba_captura(self, nb):
        aba = ttk.Frame(nb)
        nb.add(aba, text="2 · Captura")
        esq = ttk.Frame(aba)
        esq.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        dir_ = ttk.Frame(aba, width=340)
        dir_.pack(side="right", fill="y", padx=10, pady=10)
        dir_.pack_propagate(False)

        # Canvas, não Label: um Label dimensiona-se pela imagem que recebe, e como
        # o quadro era escalado pela largura do widget isso realimentava — a cada
        # quadro a imagem crescia um pouco e tomava a janela. O Canvas ignora o
        # tamanho do conteúdo, então o laço não existe.
        self.canvas_preview = tk.Canvas(esq, bg="#111", highlightthickness=0,
                                        width=640, height=360)
        self.canvas_preview.pack(fill="both", expand=True)
        self.canvas_preview.create_text(320, 180, text="(inicie a câmera)",
                                        fill="#888", tags="placeholder")
        self.lbl_info = ttk.Label(esq, text="—", anchor="w")
        self.lbl_info.pack(fill="x", pady=(6, 2))
        self.log_captura = tk.Text(esq, height=7, state="disabled", wrap="word")
        self.log_captura.pack(fill="x")

        c = ttk.LabelFrame(dir_, text="Câmera")
        c.pack(fill="x")
        self.v_cam = tk.StringVar(value="0")
        self.v_backend = tk.StringVar(value="dshow" if sys.platform.startswith("win") else "auto")
        self.v_res = tk.StringVar(value="1280x720")
        lin = ttk.Frame(c)
        lin.pack(fill="x", padx=8, pady=4)
        ttk.Label(lin, text="índice").pack(side="left")
        ttk.Entry(lin, textvariable=self.v_cam, width=5).pack(side="left", padx=6)
        ttk.Button(lin, text="Procurar", command=self.procurar_cams).pack(side="left")
        for rot, var, vals in (("backend", self.v_backend, sorted(BACKENDS)),
                               ("resolução", self.v_res, RESOLUCOES_COMUNS)):
            lin = ttk.Frame(c)
            lin.pack(fill="x", padx=8, pady=4)
            ttk.Label(lin, text=rot, width=10).pack(side="left")
            ttk.Combobox(lin, textvariable=var, values=vals, width=14).pack(side="left")
        ttk.Label(c, text="use a MESMA resolução dos experimentos:\nintrínsecos não escalam entre modos",
                  foreground=COR_ALERTA, justify="left").pack(anchor="w", padx=8, pady=(0, 6))

        fo = ttk.LabelFrame(dir_, text="Foco (a webcam ignora a trava automática)")
        fo.pack(fill="x", pady=10)
        lin = ttk.Frame(fo)
        lin.pack(fill="x", padx=8, pady=4)
        self.v_foco = tk.StringVar()
        ttk.Label(lin, text="valor").pack(side="left")
        ttk.Entry(lin, textvariable=self.v_foco, width=7).pack(side="left", padx=6)
        ttk.Button(lin, text="Aplicar", command=self.aplicar_foco).pack(side="left")
        ttk.Button(fo, text="Varrer e escolher o melhor",
                   command=self.varrer_foco).pack(fill="x", padx=8, pady=(2, 4))
        ttk.Label(fo, text="Segure o tabuleiro parado na distância de\ntrabalho e varra. Leva ~15 s.",
                  justify="left", foreground="#666").pack(anchor="w", padx=8, pady=(0, 6))

        k = ttk.LabelFrame(dir_, text="Critérios de aceite do quadro")
        k.pack(fill="x", pady=10)
        self.v_mincantos = tk.StringVar(value="12")
        self.v_nitidez = tk.StringVar(value="120")
        self.v_maxbin = tk.StringVar(value="3")
        for i, (rot, var) in enumerate((("mín. cantos", self.v_mincantos),
                                        ("nitidez mín.", self.v_nitidez),
                                        ("máx. por bin", self.v_maxbin))):
            ttk.Label(k, text=rot).grid(row=i, column=0, sticky="w", padx=8, pady=3)
            ttk.Entry(k, textvariable=var, width=8).grid(row=i, column=1, padx=8, pady=3)

        a = ttk.Frame(dir_)
        a.pack(fill="x")
        self.btn_iniciar = ttk.Button(a, text="Iniciar câmera (sessão nova)",
                                      command=self.iniciar_captura)
        self.btn_iniciar.pack(fill="x", pady=2)
        ttk.Button(a, text="Continuar sessão existente…",
                   command=self.continuar_sessao).pack(fill="x", pady=2)
        self.btn_parar = ttk.Button(a, text="Parar e salvar sessão", command=self.parar_captura,
                                    state="disabled")
        self.btn_parar.pack(fill="x", pady=2)
        lin = ttk.Frame(a)
        lin.pack(fill="x", pady=2)
        ttk.Button(lin, text="Capturar (Espaço)", command=self.capturar).pack(side="left", expand=True, fill="x")
        ttk.Button(lin, text="Desfazer (U)", command=self.desfazer).pack(side="left", expand=True, fill="x")
        ttk.Button(a, text="Analisar sem gravar (A)", command=self.analisar).pack(fill="x", pady=2)

        rt = ttk.LabelFrame(dir_, text="Roteiro guiado (captura sozinho)")
        rt.pack(fill="x", pady=10)
        self.v_roteiro = tk.BooleanVar(value=True)
        ttk.Checkbutton(rt, text="seguir roteiro e gravar automaticamente",
                        variable=self.v_roteiro, command=self._sync_roteiro).pack(anchor="w", padx=8, pady=4)
        lin = ttk.Frame(rt)
        lin.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Button(lin, text="Repetir instrucao", command=lambda: self.mover_passo(0)).pack(side="left", expand=True, fill="x")
        self.lbl_passo = ttk.Label(rt, text="—", wraplength=310, justify="left")
        self.lbl_passo.pack(anchor="w", padx=8, pady=(0, 6))

        self.v_viva = tk.BooleanVar(value=True)
        ttk.Checkbutton(a, text="guia ao vivo (640 px, ~6 ms)", variable=self.v_viva,
                        command=self._sync_modo).pack(anchor="w", pady=(6, 0))
        self.v_auto = tk.BooleanVar(value=False)
        self.chk_auto = ttk.Checkbutton(a, text="captura automática (bins novos)",
                                        variable=self.v_auto, command=self._sync_modo,
                                        state="disabled")
        self.chk_auto.pack(anchor="w")
        ttk.Label(a, text="O guia mostra escala e inclinação da pose atual sobre o\n"
                          "vídeo. A avaliação que grava roda no clique, em resolução\n"
                          "plena. Desligue o guia se o vídeo engasgar.",
                  justify="left", foreground="#666").pack(anchor="w", pady=(2, 6))

        cob = ttk.LabelFrame(dir_, text="Cobertura")
        cob.pack(fill="x", pady=10)
        self.canvas_grade = tk.Canvas(cob, width=132, height=132, highlightthickness=0)
        self.canvas_grade.pack(pady=6)
        self.lbl_cob = ttk.Label(cob, text="—", justify="left")
        self.lbl_cob.pack(anchor="w", padx=8, pady=(0, 4))
        self.lbl_faltas = ttk.Label(cob, text="", foreground=COR_ALERTA, wraplength=300, justify="left")
        self.lbl_faltas.pack(anchor="w", padx=8, pady=(0, 6))
        self.lbl_pasta = ttk.Label(dir_, text="sessão: —", wraplength=310, justify="left")
        self.lbl_pasta.pack(anchor="w")
        self._desenhar_grade(set())

    def _desenhar_grade(self, celulas):
        c = self.canvas_grade
        c.delete("all")
        for i in range(9):
            x0, y0 = (i % 3) * 44 + 2, (i // 3) * 44 + 2
            c.create_rectangle(x0, y0, x0 + 40, y0 + 40,
                               fill="#2e8b57" if i in celulas else "#e6e6e6", outline="#999")

    def _sync_modo(self):
        viva = self.v_viva.get()
        self.chk_auto.configure(state="normal" if viva else "disabled")
        if not viva:
            self.v_auto.set(False)
        if self.loop:
            (self.loop.detectar_ao_vivo.set if viva else self.loop.detectar_ao_vivo.clear)()
            (self.loop.auto.set if self.v_auto.get() else self.loop.auto.clear)()

    def procurar_cams(self):
        self.status("procurando câmeras…")

        def worker():
            achadas = procurar_cameras(4, self.v_backend.get())
            def mostrar():
                self.status("pronto")
                self.log(self.log_captura, f"câmeras que responderam: {achadas or 'nenhuma'}\n")
                if achadas:
                    self.v_cam.set(str(achadas[0]))
            self.fila_ui.put(mostrar)

        threading.Thread(target=worker, daemon=True).start()

    def continuar_sessao(self):
        """Acrescenta vistas a uma sessão já existente.

        Cobertura se completa em várias idas à câmera; forçar uma pasta nova a
        cada vez obrigaria a recomeçar do zero ou a juntar pastas na mão.
        """
        if self.loop:
            messagebox.showinfo("Continuar", "pare a captura atual primeiro")
            return
        d = filedialog.askdirectory(initialdir=str(RAIZ / "capturas"),
                                    title="Escolha a pasta da sessão a continuar")
        if not d:
            return
        pasta = Path(d)
        n = len(list(pasta.glob("img_*.png")))
        if not (pasta / "sessao.json").exists() and n == 0:
            if not messagebox.askyesno("Continuar", f"{pasta.name} não parece uma sessão "
                                                    f"(sem sessao.json e sem imagens). Usar assim mesmo?"):
                return
        self.pasta_continuar = pasta
        self.log(self.log_captura, f"\n[ok] próxima captura vai SOMAR a {pasta} ({n} vistas)\n")
        self.iniciar_captura()

    def iniciar_captura(self):
        if self.loop:
            return
        caminho = Path(self.var_tabuleiro.get())
        if not caminho.exists():
            messagebox.showerror("Tabuleiro", "gere o tabuleiro na aba 1 antes de capturar")
            return
        try:
            larg, alt = (int(v) for v in self.v_res.get().lower().split("x"))
        except ValueError:
            messagebox.showerror("Resolução", "use o formato LARGURAxALTURA, ex.: 1280x720")
            return

        cfg = ConfigTabuleiro.carregar(caminho)
        quadrado, marcador, fonte = escala_efetiva(cfg, permitir_nominal=True)
        board, _ = construir_board(cfg, quadrado, marcador)
        detector = novo_detector(board)
        self.btn_iniciar.configure(state="disabled")
        self.status("abrindo a câmera…")

        def worker():
            try:
                cap = abrir_camera(int(self.v_cam.get()), self.v_backend.get(), (larg, alt))
            except Exception as e:
                self.fila_ui.put(lambda msg=str(e): (self.btn_iniciar.configure(state="normal"),
                                                     self.status("pronto"),
                                                     messagebox.showerror("Câmera", msg)))
                return
            props_antes = ler_props(cap)
            trava = travar_camera(cap)
            for _ in range(10):
                cap.read()
            props_depois = ler_props(cap)
            pasta = (self.pasta_continuar or
                     RAIZ / "capturas" / time.strftime("%Y%m%d_%H%M%S"))
            self.pasta_continuar = None      # vale só para esta abertura
            sessao = SessaoCaptura(pasta, board, detector, self.v_mincantos.get(),
                                   self.v_nitidez.get(), self.v_maxbin.get())
            sessao.meta = {
                "camera": {"indice": int(self.v_cam.get()), "backend": self.v_backend.get()},
                "props_antes_travar": props_antes, "props_depois_travar": props_depois,
                "trava": trava,
                "resolucao_efetiva": [int(props_depois["FRAME_WIDTH"]), int(props_depois["FRAME_HEIGHT"])],
                "tabuleiro": str(caminho), "fonte_escala_na_captura": fonte,
                "interface": "gui", "iniciado_por": "app.py", "gerado_em": agora(),
            }

            def ligar():
                self.cap, self.sessao = cap, sessao
                self.loop = LoopCaptura(cap, sessao, self.fila_frames)
                self._sync_modo()
                self._sync_roteiro()
                self.log(self.log_captura, aceleracao.texto_resumo() + "\n")
                self.loop.start()
                self.btn_parar.configure(state="normal")
                self.lbl_pasta.configure(text=f"sessão: {pasta}")
                self.status("capturando")
                self.log(self.log_captura, "\n--- trava da câmera (pedido -> lido) ---\n")
                for nome, d in trava.items():
                    self.log(self.log_captura,
                             f"  {'ok ' if d['obedecido'] else '!! '}{nome:15s} "
                             f"pedido={d['pedido']:<8g} lido={d['lido']:<8g}\n")
                if any(not d["obedecido"] for d in trava.values()):
                    self.log(self.log_captura,
                             "  !! o driver ignorou algum pedido. Trave foco/exposição pelo app\n"
                             "     da câmera do Windows e reinicie — autofoco ligado invalida f.\n")
                res = (int(props_depois["FRAME_WIDTH"]), int(props_depois["FRAME_HEIGHT"]))
                if max(res) > self.loop.lado_guia:
                    self.log(self.log_captura,
                             f"[i] guia ao vivo detecta em {self.loop.lado_guia} px de lado; o CLIQUE\n"
                             f"    detecta em {res[0]}x{res[1]} cheio, igual ao que calibrar.py fará\n")
                if res != (larg, alt):
                    self.log(self.log_captura,
                             f"  !! resolução pedida {larg}x{alt}, entregue {res[0]}x{res[1]} — "
                             f"a calibração vale para a ENTREGUE\n")
            self.fila_ui.put(ligar)

        threading.Thread(target=worker, daemon=True).start()

    def _sync_roteiro(self):
        if not self.loop:
            return
        if self.v_roteiro.get():
            self.loop.roteiro_ativo.set()
            self.loop.detectar_ao_vivo.set()   # o roteiro precisa do guia
            self.v_viva.set(True)
            p = self.loop.passo_atual()
            if p:
                self.log(self.log_captura, f"[roteiro] agora: {p.descricao}\n")
        else:
            self.loop.roteiro_ativo.clear()

    def mover_passo(self, delta):
        if self.loop:
            self.loop.avancar_passo(delta, motivo="  (pulado)" if delta > 0 else "  (voltou)")

    def aplicar_foco(self):
        if not self.loop:
            return
        try:
            self.loop.foco_manual = float(self.v_foco.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Foco", "valor inválido")

    def varrer_foco(self):
        if self.loop:
            self.loop.pedir_varredura_foco.set()

    def capturar(self):
        if self.loop:
            self.loop.pedir_captura.set()

    def analisar(self):
        if self.loop:
            self.loop.pedir_analise.set()

    def desfazer(self):
        if self.loop:
            self.loop.pedir_desfazer.set()

    def _atalho(self, acao):
        """Atalhos só valem na aba de captura e fora de campos de texto."""
        if isinstance(self.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
            return
        if self.nb.index(self.nb.select()) == 1:
            acao()

    @staticmethod
    def _faltas_curtas(r):
        """Placar do que falta, COM contagem, para o progresso ser visível.

        Sem acento: cv2.putText não desenha acentuação.
        """
        m, f = METAS_COBERTURA, []
        if r["n_views"] < m["min_views"]:
            f.append(f"vistas {r['n_views']}/{m['min_views']}")
        for k in ("pequeno", "medio", "grande"):
            tem = r["por_escala"].get(k, 0)
            if tem < m["min_por_escala"]:
                f.append(f"{k} {tem}/{m['min_por_escala']}")
        if r["n_inclinado"] < m["min_inclinado"]:
            f.append(f"tilt>15 {r['n_inclinado']}/{m['min_inclinado']}")
        if r["n_muito_inclinado"] < m["min_muito_inclinado"]:
            f.append(f"tilt>35 {r['n_muito_inclinado']}/{m['min_muito_inclinado']}")
        if r["celulas_faltando"]:
            f.append("celulas " + ",".join(str(c) for c in r["celulas_faltando"]))
        return tuple(f)

    def _atualizar_cobertura(self, snap):
        r, m = snap["resumo"], METAS_COBERTURA
        if self.loop is not None:
            self.loop.faltando = self._faltas_curtas(r)
            self.loop.cobertura_ok = not self.loop.faltando
        self._desenhar_grade(snap["celulas"])
        self.lbl_cob.configure(text=(
            f"vistas {r['n_views']}/{m['min_views']}    células {r['celulas_cobertas']}/9\n"
            f"inclinadas {r['n_inclinado']}/{m['min_inclinado']}    "
            f"muito incl. {r['n_muito_inclinado']}/{m['min_muito_inclinado']}\n"
            + "    ".join(f"{k} {r['por_escala'].get(k, 0)}/{m['min_por_escala']}"
                          for k in ("pequeno", "medio", "grande"))))
        atende, faltas = cobertura_atende(r)
        self.lbl_faltas.configure(text="cobertura completa" if atende else "faltam: " + "; ".join(faltas),
                                  foreground=COR_OK if atende else COR_ALERTA)
        res = snap.get("resolucao", ("?", "?"))
        ms = snap.get("ms_det", 0)
        custo = f"{res[0]}x{res[1]}" + (f" · detecção {ms:.0f} ms" if ms else "")
        if self.loop is not None:
            p = self.loop.passo_atual()
            if p is None:
                self.lbl_passo.configure(text="roteiro concluido" if self.v_roteiro.get() else "—")
            else:
                faltas = self.loop.faltas_passo
                self.lbl_passo.configure(
                    text=f"vista {p.n}\n{p.descricao}\n"
                         + ("\n".join("• " + f for f in faltas[:3]) if faltas else "• pronto — segure"))
        a = snap.get("aval") or snap.get("ultimo_aval")
        recente = snap.get("aval") is not None

        if a is None:
            self.lbl_info.configure(
                text=f"prévia sem detecção — Espaço captura e avalia, A analisa sem gravar"
                     f"   |   {custo}", foreground="#666")
            return
        prefixo = "" if recente else "última avaliação: "
        if a["cantos"] is None:
            self.lbl_info.configure(text=f"{prefixo}sem tabuleiro no quadro   |   {custo}",
                                    foreground=COR_ALERTA)
        else:
            self.lbl_info.configure(
                text=(f"{prefixo}cantos {a['n_cantos']} | nitidez {a['nitidez']:.0f} | "
                      f"tilt {a['tilt']:.0f}° | {a['classe']['escala']}/{a['classe']['tilt']} | "
                      f"bin {a['no_bin']}/{self.v_maxbin.get()} | {a['motivo']}   |   {custo}"),
                foreground=COR_OK if a["capturavel"] else COR_ALERTA)

    def parar_captura(self):
        if not self.loop:
            return
        self.loop.parar.set()
        self.loop.join(timeout=2.0)
        if self.cap:
            self.cap.release()
        meta = dict(getattr(self.sessao, "meta", {}))
        meta["props_amostradas_durante_a_sessao"] = self.loop.resumo_props()
        try:
            alvo = self.sessao.salvar(meta)
        except Exception as e:
            self.log(self.log_captura, f"[ERRO] não consegui salvar sessao.json: {e}\n")
            alvo = "(não salvo)"
        if not self.loop.is_alive():
            self.log(self.log_captura,
                     "[nota] a thread de captura já estava parada — veja acima se houve erro\n")
        for nome, d in meta["props_amostradas_durante_a_sessao"].items():
            if d.get("observavel") and not d.get("constante"):
                self.log(self.log_captura,
                         f"[ATENÇÃO] {nome} VARIOU durante a sessão: {d['valores']}\n"
                         f"          Isso muda os intrínsecos entre vistas — a calibração\n"
                         f"          resultante mistura estados ópticos diferentes.\n")
            elif d.get("observavel"):
                self.log(self.log_captura, f"[ok] {nome} constante em {d['valores'][0]:g}\n")
            else:
                self.log(self.log_captura, f"[?] {nome} não é observável neste driver\n")
        atende, faltas = self.sessao.veredicto_cobertura()
        self.log(self.log_captura, f"\n[ok] sessão salva em {alvo}\n")
        self.log(self.log_captura, json.dumps(self.sessao.resumo(), indent=2, ensure_ascii=False) + "\n")
        if atende:
            self.log(self.log_captura, "[ok] cobertura atende as metas pré-registradas\n")
        else:
            self.log(self.log_captura, "[ATENÇÃO] cobertura insuficiente — faltam: "
                                       + "; ".join(faltas) + "\n"
                     + "     Calibrar assim mede a lente só onde o tabuleiro esteve.\n")
        self.v_pasta_img.set(str(self.sessao.pasta))
        self.loop, self.cap = None, None
        self.btn_iniciar.configure(state="normal")
        self.btn_parar.configure(state="disabled")
        self.status("sessão encerrada")
        if messagebox.askyesno("Sessão encerrada", "Ir para a aba de calibração?"):
            self.nb.select(2)

    # ================= aba 3: calibrar =================
    def aba_calibrar(self, nb):
        aba = ttk.Frame(nb)
        nb.add(aba, text="3 · Calibrar")
        topo = ttk.Frame(aba)
        topo.pack(fill="x", padx=12, pady=10)

        self.v_pasta_img = tk.StringVar()
        self.v_nome_cam = tk.StringVar(value="webcam_pc")
        self.v_particoes = tk.StringVar(value="20")
        self.v_boot = tk.StringVar(value="150")
        self.v_nominal = tk.BooleanVar(value=False)

        lin = ttk.Frame(topo)
        lin.pack(fill="x", pady=3)
        ttk.Label(lin, text="pasta das vistas", width=16).pack(side="left")
        ttk.Entry(lin, textvariable=self.v_pasta_img).pack(side="left", fill="x", expand=True)
        ttk.Button(lin, text="Procurar", command=lambda: self._escolher_pasta(self.v_pasta_img)).pack(side="left", padx=6)

        lin = ttk.Frame(topo)
        lin.pack(fill="x", pady=3)
        for rot, var, larg in (("nome da câmera", self.v_nome_cam, 16),
                               ("partições", self.v_particoes, 6),
                               ("bootstrap", self.v_boot, 6)):
            ttk.Label(lin, text=rot).pack(side="left", padx=(0, 4))
            ttk.Entry(lin, textvariable=var, width=larg).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(lin, text="assumir quadrado nominal (resultado NÃO rastreável)",
                        variable=self.v_nominal).pack(side="left")

        lin = ttk.Frame(topo)
        lin.pack(fill="x", pady=(8, 0))
        ttk.Button(lin, text="Calibrar", command=self.calibrar).pack(side="left")
        ttk.Button(lin, text="Abrir relatório", command=self.abrir_relatorio).pack(side="left", padx=8)

        meio = ttk.Frame(aba)
        meio.pack(fill="both", expand=True, padx=12, pady=6)
        v = ttk.LabelFrame(meio, text="Veredicto contra a régua pré-registrada")
        v.pack(side="left", fill="both", expand=True)
        self.tv = ttk.Treeview(v, columns=("medido", "res"), show="tree headings", height=9)
        self.tv.heading("#0", text="critério")
        self.tv.heading("medido", text="medido")
        self.tv.heading("res", text="")
        self.tv.column("#0", width=230)
        self.tv.column("medido", width=210)
        self.tv.column("res", width=110)
        self.tv.tag_configure("ok", foreground=COR_OK)
        self.tv.tag_configure("falha", foreground=COR_ERRO)
        self.tv.pack(fill="both", expand=True, padx=6, pady=6)
        self.lbl_intrinsecos = ttk.Label(v, text="—", justify="left", font=("Consolas", 9))
        self.lbl_intrinsecos.pack(anchor="w", padx=8, pady=(0, 8))

        self.log_calibrar = tk.Text(aba, height=12, state="disabled", wrap="word")
        self.log_calibrar.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    def _escolher_pasta(self, var):
        d = filedialog.askdirectory(initialdir=str(RAIZ))
        if d:
            var.set(d)

    def _escolher_arquivo(self, var, tipos):
        f = filedialog.askopenfilename(initialdir=str(RAIZ), filetypes=tipos)
        if f:
            var.set(f)

    def calibrar(self):
        if not self.v_pasta_img.get():
            messagebox.showerror("Calibrar", "escolha a pasta com as vistas")
            return
        args = ["calibrar.py", "--imagens", self.v_pasta_img.get(),
                "--tabuleiro", self.var_tabuleiro.get(), "--saida", str(RAIZ / "saida"),
                "--nome-camera", self.v_nome_cam.get(),
                "--particoes", self.v_particoes.get(), "--bootstrap", self.v_boot.get()]
        if self.v_nominal.get():
            args.append("--assumir-nominal")
        self.rodar_script(args, self.log_calibrar, ao_terminar=lambda rc: self.mostrar_calibracao(),
                          titulo="calibrar")

    def mostrar_calibracao(self):
        alvo = RAIZ / "saida" / f"calibracao_{self.v_nome_cam.get()}.json"
        if not alvo.exists():
            return
        r = json.loads(alvo.read_text(encoding="utf-8"))
        self.tv.delete(*self.tv.get_children())
        for k, v in r["veredicto"].items():
            self.tv.insert("", "end", text=k, values=(v["medido"], "APROVADO" if v["aprovado"] else "REPROVADO"),
                           tags=("ok" if v["aprovado"] else "falha",))
        ic = r.get("ic95_bootstrap") or {}
        linhas = []
        for nome in ("fx", "fy", "cx", "cy"):
            faixa = (f"  IC95 [{ic[nome]['ic95'][0]:.2f}, {ic[nome]['ic95'][1]:.2f}]"
                     if nome in ic else "")
            linhas.append(f"{nome} = {r[nome]:10.3f}{faixa}")
        linhas.append(f"modelo = {r['modelo_distorcao']}   RMS = {r['rms_global_px']:.4f} px   "
                      f"P90 = {r['erro_reprojecao']['p90_px']:.3f} px")
        linhas.append(f"escala = {r['escala']['quadrado_mm']} mm ({r['escala']['fonte']})   "
                      f"vistas = {r['n_vistas']}")
        self.lbl_intrinsecos.configure(text="\n".join(linhas))
        self.v_calib.set(str(alvo))
        self.status("calibração " + ("APROVADA" if r["aprovado"] else "REPROVADA — recapturar"))

    def abrir_relatorio(self):
        self.abrir_no_sistema(RAIZ / "saida" / f"relatorio_{self.v_nome_cam.get()}.md")

    # ================= aba 4: validar =================
    def aba_validar(self, nb):
        aba = ttk.Frame(nb)
        nb.add(aba, text="4 · Validar")
        topo = ttk.Frame(aba)
        topo.pack(fill="x", padx=12, pady=10)

        self.v_calib = tk.StringVar(value=str(RAIZ / "saida" / "calibracao_webcam_pc.json"))
        self.v_pasta_val = tk.StringVar()
        self.v_dist_real = tk.StringVar()
        self.v_img_dist = tk.StringVar()

        for rot, var, cmd in (("calibração (json)", self.v_calib,
                               lambda: self._escolher_arquivo(self.v_calib, [("JSON", "*.json")])),
                              ("vistas NOVAS", self.v_pasta_val,
                               lambda: self._escolher_pasta(self.v_pasta_val))):
            lin = ttk.Frame(topo)
            lin.pack(fill="x", pady=3)
            ttk.Label(lin, text=rot, width=16).pack(side="left")
            ttk.Entry(lin, textvariable=var).pack(side="left", fill="x", expand=True)
            ttk.Button(lin, text="Procurar", command=cmd).pack(side="left", padx=6)

        lin = ttk.Frame(topo)
        lin.pack(fill="x", pady=3)
        ttk.Label(lin, text="distância medida com trena (mm)").pack(side="left")
        ttk.Entry(lin, textvariable=self.v_dist_real, width=10).pack(side="left", padx=6)
        ttk.Label(lin, text="na imagem").pack(side="left")
        ttk.Entry(lin, textvariable=self.v_img_dist, width=18).pack(side="left", padx=6)
        ttk.Button(lin, text="Validar", command=self.validar).pack(side="left", padx=12)

        ttk.Label(topo, text="Use uma sessão de captura DIFERENTE da que gerou a calibração — "
                             "o erro do próprio ajuste é otimista por construção.",
                  foreground=COR_ALERTA, wraplength=1000, justify="left").pack(anchor="w", pady=(6, 0))

        self.lbl_val = ttk.Label(aba, text="—", justify="left", font=("Consolas", 9))
        self.lbl_val.pack(anchor="w", padx=14, pady=6)
        self.lbl_img_val = ttk.Label(aba, text="", anchor="center")
        self.lbl_img_val.pack(fill="both", expand=True, padx=12)
        self.log_validar = tk.Text(aba, height=10, state="disabled", wrap="word")
        self.log_validar.pack(fill="x", padx=12, pady=(6, 10))

    def validar(self):
        if not self.v_pasta_val.get():
            messagebox.showerror("Validar", "escolha a pasta com as vistas novas")
            return
        args = ["validar.py", "--calibracao", self.v_calib.get(),
                "--imagens", self.v_pasta_val.get(),
                "--tabuleiro", self.var_tabuleiro.get(), "--saida", str(RAIZ / "saida")]
        if self.v_dist_real.get() and self.v_img_dist.get():
            args += ["--distancia-real-mm", self.v_dist_real.get(),
                     "--imagem-distancia", self.v_img_dist.get()]
        self.rodar_script(args, self.log_validar, ao_terminar=lambda rc: self.mostrar_validacao(),
                          titulo="validar")

    def mostrar_validacao(self):
        alvo = RAIZ / "saida" / "validacao.json"
        if not alvo.exists():
            return
        r = json.loads(alvo.read_text(encoding="utf-8"))
        rp, rt = r["reprojecao_independente"], r["retidao_apos_undistort"]
        linhas = [
            f"vistas independentes: {r['n_vistas']}",
            f"reprojeção   mediana {rp['mediana_px']:.3f} px   P90 {rp['p90_px']:.3f}   "
            f">1px {rp['frac_acima_1px']*100:.1f}%",
            f"retidão      mediana {rt['mediana_px']:.3f} px   P90 {rt['p90_px']:.3f}   "
            f"(0 = linhas retas após corrigir a distorção)",
        ]
        if "teste_metrico" in r:
            t = r["teste_metrico"]
            linhas.append(f"métrico      PnP {t['distancia_pnp_mm']:.0f} mm vs trena "
                          f"{t['distancia_trena_mm']:.0f} mm  =>  {t['erro_mm']:+.0f} mm "
                          f"({t['erro_relativo']*100:+.2f}%)")
        else:
            linhas.append("métrico      não executado (informe a distância da trena)")
        self.lbl_val.configure(text="\n".join(linhas))
        img = cv2.imread(str(RAIZ / "saida" / "undistort_antes_depois.png"))
        if img is not None:
            self._foto_val = para_photo(img, largura_max=1000)
            self.lbl_img_val.configure(image=self._foto_val, text="")

    # ================= encerramento =================
    def fechar(self):
        # A janela TEM de fechar. Antes, um erro ao salvar a sessão propagava e
        # o destroy() nunca era alcançado — o app ficava impossível de fechar.
        if self.loop:
            if not messagebox.askyesno("Sair", "A captura está ativa. Parar e salvar a sessão?"):
                return
            try:
                self.parar_captura()
            except Exception as e:
                print("erro ao encerrar a sessão:", e)
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
