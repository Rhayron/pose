"""
Roteiro de captura: a sequência de poses como critérios objetivos.

Em vez de você traduzir "canto superior esquerdo, bem inclinado" para o que o
app mede, o roteiro carrega os critérios e o app diz, em número, o quanto falta
para o passo atual — e dispara a captura sozinho quando eles são atendidos.

Célula: grade 3x3, numerada da esquerda para a direita, de cima para baixo.

    0 1 2
    3 4 5
    6 7 8
"""

from __future__ import annotations

from dataclasses import dataclass

from nucleo import BINS_ESCALA

NOME_CELULA = {
    0: "canto superior esquerdo", 1: "meio de cima", 2: "canto superior direito",
    3: "meio da esquerda", 4: "centro", 5: "meio da direita",
    6: "canto inferior esquerdo", 7: "meio de baixo", 8: "canto inferior direito",
}


@dataclass
class Passo:
    n: int
    escala: str | None          # 'pequeno' | 'medio' | 'grande' | None (qualquer)
    celula: int | None
    tilt_min: float
    tilt_max: float

    @property
    def descricao(self) -> str:
        """Só menciona o que este passo EXIGE — o resto fica livre de propósito."""
        partes = []
        tam = {"pequeno": "AFASTE (longe)", "medio": "distancia MEDIA",
               "grande": "APROXIME (perto)"}.get(self.escala)
        if tam:
            partes.append(tam)
        if self.celula is not None:
            partes.append(f"alcance o {NOME_CELULA[self.celula]}")
        if self.tilt_min >= 30:
            partes.append(f"INCLINE FORTE (>{self.tilt_min:.0f} graus)")
        elif self.tilt_min >= 12:
            partes.append(f"incline ({self.tilt_min:.0f}-{self.tilt_max:.0f} graus)")
        elif self.tilt_max <= 25:
            partes.append("de frente")
        return " · ".join(partes) if partes else "qualquer pose valida"


def faixa_area(escala):
    for lo, hi, nome in BINS_ESCALA:
        if nome == escala:
            return lo, hi
    return 0.0, 1.0


def padrao() -> list[Passo]:
    """25 poses que fecham todas as metas, com folga."""
    p, n = [], 0

    def add(escala, celula, tmin, tmax):
        nonlocal n
        n += 1
        p.append(Passo(n, escala, celula, tmin, tmax))

    # MEDIO — cobre as nove células; as quatro dos cantos bem inclinadas
    for c in (4, 1, 7, 3, 5):
        add("medio", c, 0, 20)
    for c in (0, 2, 6, 8):
        add("medio", c, 35, 75)

    # PERTO — o que amarra o ponto principal; nas bordas o tabuleiro pode
    # (e deve) sair parcialmente do quadro
    add("grande", 4, 0, 20)
    add("grande", 4, 35, 75)
    add("grande", 4, 35, 75)
    for c in (3, 5, 1, 7):
        add("grande", c, 15, 45)
    add("grande", 8, 0, 25)

    # LONGE — completa a variedade de escala
    for c in (0, 2, 6, 8):
        add("pequeno", c, 0, 20)
    add("pequeno", 4, 0, 20)
    for c in (4, 3, 5):
        add("pequeno", c, 35, 75)
    return p


def proximo(resumo, metas=None) -> Passo | None:
    """Passo adaptativo: pede UMA coisa por vez, a mais urgente que falta.

    O roteiro fixo pedia escala, célula e inclinação juntas — e elas brigam:
    inclinar 40 graus encolhe a área projetada em ~25%, então o tabuleiro cai
    de MEDIO para PEQUENO no mesmo gesto que atende a inclinação. Com uma
    exigência por vez, cada passo é alcançável e a sequência sempre converge.

    Ordem: inclinação forte primeiro (a mais difícil de combinar), depois
    escalas, células, inclinação média e por fim volume de vistas.
    """
    from nucleo import METAS_COBERTURA
    m = metas or METAS_COBERTURA
    n = resumo["n_views"] + 1

    if resumo["n_muito_inclinado"] < m["min_muito_inclinado"]:
        return Passo(n, None, None, 35, 75)
    for esc in ("grande", "medio", "pequeno"):
        if resumo["por_escala"].get(esc, 0) < m["min_por_escala"]:
            return Passo(n, esc, None, 0, 89)
    if resumo["celulas_faltando"]:
        return Passo(n, None, resumo["celulas_faltando"][0], 0, 89)
    if resumo["n_inclinado"] < m["min_inclinado"]:
        return Passo(n, None, None, 15, 89)
    if resumo["n_views"] < m["min_views"]:
        return Passo(n, None, None, 0, 89)
    return None


def avaliar(passo: Passo, aval) -> tuple[bool, list[str]]:
    """Devolve (atende, faltas em NÚMERO).

    As faltas são quantitativas de propósito: "area 4.9% (precisa 6.0-20.0%)"
    diz o que fazer; "precisa MEDIO" não diz.
    """
    if not aval or aval.get("cantos") is None:
        return False, ["sem tabuleiro"]
    faltas = []
    if passo.escala:
        lo, hi = faixa_area(passo.escala)
        a = aval.get("area", 0.0)
        if not (lo <= a < hi):
            alvo = f"{lo*100:.0f}-{min(hi,1.0)*100:.0f}%"
            seta = "aproxime" if a < lo else "afaste"
            faltas.append(f"area {a*100:.1f}% (precisa {alvo}) -> {seta}")
    # A exigência é COBRIR a célula (ter cantos nela), não centrar o tabuleiro
    # nela: em escala média ou grande, levar o CENTRO até um canto do quadro
    # exigiria metade do alvo fora da imagem. E o que amarra a distorção é
    # onde caem os pontos medidos, não onde está o centro.
    tocadas = aval["classe"].get("celulas_tocadas") or [aval["classe"]["celula"]]
    if passo.celula is not None and passo.celula not in tocadas:
        faltas.append(f"cobrindo {sorted(tocadas)} (precisa alcancar a {passo.celula}: "
                      f"{NOME_CELULA[passo.celula]})")
    t = aval.get("tilt", 0.0)
    if not (passo.tilt_min <= t <= passo.tilt_max):
        seta = "incline mais" if t < passo.tilt_min else "incline menos"
        faltas.append(f"tilt {t:.0f} graus (precisa {passo.tilt_min:.0f}-"
                      f"{passo.tilt_max:.0f}) -> {seta}")
    if not aval.get("capturavel"):
        faltas.append(aval.get("motivo", "nao capturavel"))
    return (not faltas), faltas
