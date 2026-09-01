"""Testes da aquisição, com fonte sintética de temporização conhecida.

Não dá para testar sincronismo com uma câmera real: não se sabe a verdade. Aqui
a fonte é sintética, o instante do evento é escolhido por nós, e o teste
verifica se o código recupera o número que foi plantado.

O que é verificado:

1. o marcador cai no quadro certo do fluxo;
2. a detecção de evento luminoso acha o quadro do degrau;
3. a interpolação sub-quadro recupera a fração plantada;
4. um degrau abaixo do limiar NÃO é reportado como evento;
5. a qualidade do sincronismo degrada corretamente quando só há o clique;
6. quadro descartado por fila não quebra a correspondência índice↔carimbo;
7. quadro perdido é contado a partir do intervalo, não da contagem nominal.

    python teste_aquisicao.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from camera import Estatisticas  # noqa: E402
from sessao import (  # noqa: E402
    DEGRAU_EVENTO_MIN,
    _qualidade_sincronismo,
    detectar_evento_luminoso,
)

FALHAS: list[str] = []


def checar(condicao: bool, descricao: str) -> None:
    print(f"  [{'ok  ' if condicao else 'FALHA'}] {descricao}")
    if not condicao:
        FALHAS.append(descricao)


def fluxo_sintetico(
    n: int = 120,
    fps: float = 60.0,
    quadro_do_evento: int | None = None,
    fracao: float = 0.0,
    brilho_baixo: float = 20.0,
    brilho_alto: float = 200.0,
    perdidos: tuple[int, ...] = (),
) -> list[dict]:
    """Gera a tabela de quadros que a Gravacao produziria.

    `fracao` é a parte da janela de exposição do quadro de transição em que a
    luz já estava acesa. É o valor que a interpolação deve recuperar.
    """
    periodo_ns = int(1e9 / fps)
    quadros: list[dict] = []
    t = 1_000_000_000
    indice = 0
    for i in range(n):
        if i in perdidos:
            t += periodo_ns
            continue
        if quadro_do_evento is None or i < quadro_do_evento:
            brilho = brilho_baixo
        elif i == quadro_do_evento and fracao > 0:
            brilho = brilho_baixo + fracao * (brilho_alto - brilho_baixo)
        else:
            brilho = brilho_alto
        quadros.append({"i": indice, "indice_fonte": i,
                        "monotonic_ns": t, "brilho_roi": round(brilho, 3)})
        t += periodo_ns
        indice += 1
    return quadros


def teste_marcador() -> None:
    print("\n1. Marcador cai no quadro certo")
    quadros = fluxo_sintetico(n=60)
    periodo_ns = quadros[1]["monotonic_ns"] - quadros[0]["monotonic_ns"]

    # Clique 2 ms depois do quadro 30.
    alvo = quadros[30]["monotonic_ns"] + 2_000_000
    mais_proximo = min(quadros, key=lambda q: abs(q["monotonic_ns"] - alvo))
    checar(mais_proximo["i"] == 30, "clique logo após um quadro casa com esse quadro")

    # Clique a 90% do período: o quadro seguinte é o mais próximo.
    alvo = quadros[30]["monotonic_ns"] + int(periodo_ns * 0.9)
    mais_proximo = min(quadros, key=lambda q: abs(q["monotonic_ns"] - alvo))
    checar(mais_proximo["i"] == 31, "clique perto do fim do período casa com o próximo")


def teste_evento_luminoso() -> None:
    print("\n2. Detecção do evento luminoso")

    quadros = fluxo_sintetico(n=120, quadro_do_evento=70, fracao=0.0)
    ev = detectar_evento_luminoso(quadros)
    checar(ev["detectado"], "detecta o degrau")
    checar(ev["sentido"] == "acendeu", "identifica o sentido")
    checar(ev["quadro_depois"] == 70,
           f"aponta o quadro 70 (achou {ev.get('quadro_depois')})")
    checar(not ev["interpolado"], "não interpola quando o degrau é abrupto")

    print("\n3. Interpolação sub-quadro")
    for fracao_real in (0.25, 0.50, 0.75):
        quadros = fluxo_sintetico(n=120, quadro_do_evento=70, fracao=fracao_real)
        ev = detectar_evento_luminoso(quadros)
        recuperada = ev.get("fracao_exposicao")
        ok = ev["interpolado"] and abs(recuperada - fracao_real) < 0.02
        checar(ok, f"recupera fração {fracao_real} (achou {recuperada})")

        # O instante interpolado tem de cair entre os dois quadros.
        antes = quadros[69]["monotonic_ns"]
        depois = quadros[70]["monotonic_ns"]
        checar(antes <= ev["monotonic_ns"] <= depois,
               f"  instante interpolado fica entre os quadros vizinhos")

    print("\n4. Degrau pequeno não vira evento")
    quadros = fluxo_sintetico(n=120, quadro_do_evento=70, fracao=0.0,
                              brilho_baixo=100.0,
                              brilho_alto=100.0 + DEGRAU_EVENTO_MIN * 0.5)
    ev = detectar_evento_luminoso(quadros)
    checar(not ev["detectado"], "ruído abaixo do limiar não é reportado como evento")

    quadros = fluxo_sintetico(n=120)  # sem evento nenhum
    ev = detectar_evento_luminoso(quadros)
    checar(not ev["detectado"], "fluxo sem degrau não inventa evento")


def teste_qualidade() -> None:
    print("\n5. Qualidade do sincronismo é declarada corretamente")

    q = _qualidade_sincronismo({"detectado": False}, None, None)
    checar(q["nivel"] == "ausente", "sem evento e sem clique -> ausente")

    q = _qualidade_sincronismo({"detectado": False}, {"monotonic_ns": 1}, None)
    checar(q["nivel"] == "grosseira", "só clique -> grosseira")
    checar("NÃO" in q["base"], "  e o texto diz explicitamente o que não serve")
    checar("aviso_latencia" in q, "  avisa que a latência não foi medida")

    q = _qualidade_sincronismo(
        {"detectado": True, "interpolado": False, "incerteza_ms_estimada": 16.7},
        {"monotonic_ns": 1}, 42.0)
    checar(q["nivel"] == "um_quadro", "evento sem interpolação -> um_quadro")
    checar(q["latencia_pipeline_compensada"], "  registra que a latência foi informada")

    q = _qualidade_sincronismo(
        {"detectado": True, "interpolado": True, "incerteza_ms_estimada": 1.7},
        {"monotonic_ns": 1}, 42.0)
    checar(q["nivel"] == "fina", "evento interpolado -> fina")
    checar(q["incerteza_ms_estimada"] < 5.0, "  com incerteza na casa do milissegundo")


def teste_correspondencia_e_perdas() -> None:
    print("\n6. Correspondência índice<->carimbo e contagem de perdas")

    # A tabela é a fonte da verdade: descartar por fila remove o registro junto.
    quadros = fluxo_sintetico(n=50)
    checar([q["i"] for q in quadros] == list(range(50)),
           "índices da tabela são contíguos")

    quadros = fluxo_sintetico(n=50, perdidos=(10, 11, 30))
    checar(len(quadros) == 47, "quadros perdidos somem da tabela")
    checar([q["i"] for q in quadros] == list(range(47)),
           "índices continuam contíguos após perda")

    est = Estatisticas()
    est.n_quadros = len(quadros)
    est.intervalos_ms = [
        (quadros[i + 1]["monotonic_ns"] - quadros[i]["monotonic_ns"]) / 1e6
        for i in range(len(quadros) - 1)
    ]
    resumo = est.resumo()
    checar(resumo["quadros_perdidos_estimados"] == 3,
           f"estima 3 perdidos pelo intervalo (achou {resumo['quadros_perdidos_estimados']})")
    checar(abs(resumo["fps_medido"] - 60.0) < 0.5,
           f"fps medido pela mediana ignora as perdas ({resumo['fps_medido']})")

    print("\n7. Metadados fecham")
    quadros = fluxo_sintetico(n=120, quadro_do_evento=70, fracao=0.4)
    ev = detectar_evento_luminoso(quadros)
    doc = {
        "quadros": quadros,
        "sincronismo": {"evento_luminoso": ev,
                        "qualidade": _qualidade_sincronismo(ev, {"monotonic_ns": 1}, 42.0)},
    }
    texto = json.dumps(doc, ensure_ascii=False, allow_nan=False)
    checar(len(texto) > 0, "documento serializa em JSON sem NaN")
    checar(json.loads(texto)["sincronismo"]["qualidade"]["nivel"] == "fina",
           "sobrevive à ida e volta do JSON")


def teste_verificacao_de_foco() -> None:
    """Foco é a única propriedade que muda a geometria. O guarda tem de pegar."""
    print("\n8. Foco conferido contra o da calibração")
    from camera import FonteCamera  # noqa: PLC0415

    def montar(focus_esperado, inicial, durante):
        f = FonteCamera(focus_esperado=focus_esperado)
        f.props_antes = {"focus": inicial}
        f.amostras_props = [{"monotonic_ns": i, "focus": v}
                            for i, v in enumerate(durante)]
        return f.verificar_foco()

    v = montar(243.0, 243.0, [243.0, 243.0, 243.0])
    checar(v["confere"] and not v["alertas"],
           "foco igual ao da calibração e estável -> sem alerta")

    v = montar(243.0, 280.0, [280.0, 280.0])
    checar(not v["confere"], "foco diferente é reprovado")
    checar(any("suspeito" in a for a in v["alertas"]),
           "  e o alerta diz que o número métrico fica suspeito")
    checar(v["diferenca"] == 37.0, f"  relata a magnitude (achou {v['diferenca']})")

    v = montar(243.0, 243.0, [243.0, 255.0, 268.0])
    checar(not v["estavel_durante_a_sessao"], "foco que varia na sessão é detectado")
    checar(any("variou durante a sessão" in a for a in v["alertas"]),
           "  e o alerta aponta autofoco provavelmente ativo")

    v = montar(243.0, None, [])
    checar(any("não observável" in a for a in v["alertas"]),
           "driver que não reporta foco vira alerta, não silêncio")

    v = montar(None, 243.0, [243.0])
    checar(not v["verificado"], "sem referência no perfil, declara que não verificou")


def main() -> int:
    print("Testes da aquisição sincronizada")
    print(f"NumPy {np.__version__} | Python {sys.version.split()[0]}")

    teste_marcador()
    teste_evento_luminoso()
    teste_qualidade()
    teste_correspondencia_e_perdas()
    teste_verificacao_de_foco()

    print()
    if FALHAS:
        print(f"{len(FALHAS)} FALHA(S):")
        for f in FALHAS:
            print(f"  - {f}")
        return 1
    print("Todos os testes passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
