import sys, types, queue, time, tempfile
from pathlib import Path
import cv2

# stub minimo de tkinter so para conseguir importar app.py neste ambiente sem Tk
tk = types.ModuleType("tkinter")
class _W:
    def __init__(self,*a,**k): pass
    def __getattr__(self,n): return lambda *a,**k: None
for nome in ("Tk","Canvas","Text","StringVar","BooleanVar","Entry","Frame","Label","PhotoImage"):
    setattr(tk, nome, type(nome,(_W,),{}))
tk.__dict__.update({"END":"end"})
ttk = types.ModuleType("tkinter.ttk")
for nome in ("Notebook","Frame","Label","Button","Entry","Combobox","Checkbutton",
             "LabelFrame","Treeview","Separator","Style"):
    setattr(ttk, nome, type(nome,(_W,),{}))
for mod, nomes in (("tkinter.filedialog",("askdirectory","askopenfilename")),
                   ("tkinter.messagebox",("showerror","showinfo","askyesno"))):
    m = types.ModuleType(mod)
    for n in nomes: setattr(m, n, lambda *a,**k: None)
    sys.modules[mod] = m
sys.modules["tkinter"], sys.modules["tkinter.ttk"] = tk, ttk
tk.ttk, tk.filedialog, tk.messagebox = ttk, sys.modules["tkinter.filedialog"], sys.modules["tkinter.messagebox"]

sys.path.insert(0, ".")
import app
from nucleo import ConfigTabuleiro, construir_board, novo_detector, escala_efetiva
from captura_core import SessaoCaptura

cfg = ConfigTabuleiro.carregar(Path("saida/tabuleiro.json"))
q,m,_ = escala_efetiva(cfg, True); board,_ = construir_board(cfg,q,m); det = novo_detector(board)
quadro = cv2.resize(cv2.imread("saida/tabuleiro.png"), (1280,720))

class CapFalso:
    def __init__(self): self.n=0
    def read(self): self.n+=1; return True, quadro.copy()
    def get(self,pid): return 0.0

s = SessaoCaptura(Path(tempfile.mkdtemp())/"s", board, det, 12, 50.0, 3)
fila = queue.Queue(maxsize=1)
loop = app.LoopCaptura(CapFalso(), s, fila, largura_preview=640)

# injeta uma falha permanente na avaliacao: antes isso matava a thread
falhou = {"n":0}
orig = s.avaliar
def avaliar_quebrado(frame, reduzido=True):
    falhou["n"] += 1
    raise RuntimeError("falha simulada na deteccao")
s.avaliar = avaliar_quebrado

loop.start()
time.sleep(0.4)
loop.pedir_analise.set()
time.sleep(0.6)
vivo_apos_erro = loop.is_alive()
erro_reportado, msg = False, ""
while True:
    try:
        ev = loop.fila_eventos.get_nowait()
    except queue.Empty:
        break
    if ev.startswith("[ERRO"):
        erro_reportado, msg = True, ev

# volta ao normal: a thread tem de continuar funcionando
s.avaliar = orig
time.sleep(0.3)
loop.pedir_captura.set()
time.sleep(0.8)
gravou = len(s.registros)
eventos = []
while True:
    try: eventos.append(loop.fila_eventos.get_nowait())
    except queue.Empty: break
confirmou = any(e.startswith("+ img_") for e in eventos)
loop.parar.set(); loop.join(timeout=2)

print(f"  {'OK  ' if vivo_apos_erro else 'FALHA'} thread sobrevive a excecao no laco")
print(f"  {'OK  ' if erro_reportado else 'FALHA'} erro chega a UI pela fila   {msg if erro_reportado else ''}")
print(f"  {'OK  ' if gravou==1 else 'FALHA'} volta a gravar depois do erro ({gravou} vista)")
print(f"  {'OK  ' if confirmou else 'FALHA'} confirmacao da captura chega a UI   {[e for e in eventos if e.startswith('+')]}")
print(f"  {'OK  ' if not loop.is_alive() else 'FALHA'} para limpo quando pedido")
