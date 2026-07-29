# Passo a passo da calibração

Deixe aberto no segundo monitor. O app conduz — este arquivo é só para
consultar quando algo sair do esperado.

Estado do tabuleiro: impresso, medido e salvo (**34,00 mm/quadrado**, desvio de
impressão −2,86%, uniforme nos dois eixos).

---

## 1. Preparar a cena · 2 min

- Tabuleiro **colado em superfície rígida e plana**.
- **Luz forte e difusa sobre a folha.** A nitidez cai com o quadrado do
  contraste: metade da luz derruba a medida a um quarto. Evite reflexo
  especular e luz de fundo forte atrás do tabuleiro.
- A webcam fica parada; quem se move é o tabuleiro.
- Reserve ~10 minutos sem interrupção.

## 2. Abrir a câmera

1. `iniciar_app.bat` → aba **2 · Captura**.
2. Resolução `3840x2160`. **Fixe agora** — trocar depois invalida `fx, fy, cx, cy`.
3. **Iniciar câmera (sessão nova)**.
4. O log mostra o estado de CUDA e a resolução entregue. Se aparecer
   `!! resolução pedida … entregue …`, a calibração vale para a **entregue**.

## 3. Acertar o foco · ~15 s

O foco de fábrica estava em 326, ajustado para longe: por isso aproximar
borrava (nitidez 72 no MEDIO contra 600 no PEQUENO). Isso não se resolve
baixando o limiar — seriam cantos genuinamente fora de foco entrando na medida.

5. Apoie o tabuleiro **parado**, na distância que faz a faixa dizer `MEDIO`.
6. Clique **Varrer e escolher o melhor**.
7. Leia a varredura no log. Ela termina assim:

```
[ok] foco = 90 (nitidez 1204); lido de volta 90
[dica] limiar de nitidez sugerido: 602
```

8. Copie o limiar sugerido para `nitidez mín.` (vale na hora; a mudança fica
   registrada no `sessao.json`).
9. Se aparecer `[!!] o driver nao aceitou o valor`, pare: o foco não está sob
   controle e a estratégia muda.

## 4. Deixar o roteiro conduzir · ~8 min

10. Marque **seguir roteiro e gravar automaticamente** (já vem marcado).
11. A faixa mostra o passo e o que falta, em número:

```
PASSO 3/25: MEDIO · meio de baixo · de frente
  -> area 2.2% (precisa 6-20%) -> aproxime
  -> tilt 41 graus (precisa 0-20) -> incline menos
```

12. Ajuste até as faltas sumirem. Quando some tudo, aparece
    `SEGURE ASSIM [####]` e o app grava sozinho, em resolução plena, e avança.
13. Passo impossível: **pular >>**. Anote qual — isso é informação sobre o
    aparato. **<< passo** volta.

O roteiro tem 25 passos: 9 em MEDIO, 8 em GRANDE, 8 em PEQUENO; 9 com
inclinação acima de 35°; as nove células da grade como alvo.

**Célula = onde caem os cantos detectados**, não onde está o centro do
tabuleiro. Um tabuleiro grande cortado pela borda esquerda cobre a coluna
esquerda inteira — é assim que se alcança os cantos em escala grande.

14. Se a nitidez despencar ao aproximar (bloco GRANDE), o foco escolhido não
    cobre essa distância: **varra o foco de novo** ali e siga. A sessão terá
    dois estados ópticos — anote, porque isso precisa entrar na análise.

## 5. Encerrar

15. **Parar e salvar sessão**.
16. Leia a linha do `FOCUS`:
    - `[ok] FOCUS constante em 90` → seguir.
    - `[ATENÇÃO] FOCUS VARIOU` → descartar a sessão e refazer com foco travado.
    - `[?] não observável` → seguir, mas conferir as vistas suspeitas no passo 18.

## 6. Calibrar

17. Aba **3 · Calibrar** (a pasta já vem preenchida) → **Calibrar**. O bootstrap
    leva alguns minutos.

18. Veredicto:

| Critério | Limite | Se falhar |
| :--- | :--- | :--- |
| vistas | ≥ 25 | capturar mais |
| cobertura | 9/9 células e bins cheios | capturar o que a faixa pedir |
| RMS global | ≤ 0,50 px | ver vistas suspeitas |
| P90 do erro | ≤ 1,00 px | idem |
| erro em hold-out | ≤ 0,60 px | idem |
| largura do IC95 de `fx` | ≤ 2% | falta variedade de distância |

**Os dois números que decidem** (referência: a tentativa com 9 vistas deu
`IC95 de fx = 61%` e `cy = 786`):

- `largura_relativa_ic95_fx` tem de cair para ≤ 2%. Um IC largo significa que
  distância focal e profundidade ainda estão trocáveis entre si — sintoma de
  pouca variedade de escala, não de ruído.
- `cy` tem de subir de 786 para perto de 1080 (metade de 2160). Quem amarra o
  ponto principal são as vistas com o tabuleiro nas bordas do quadro.

Critério que falha se corrige **recapturando**, nunca relaxando o número.

## 7. Validar

19. Aba 2 → **Iniciar câmera (sessão nova)** → desmarque o roteiro → ~10 vistas
    variadas, à mão. Precisa ser sessão **nova**: o erro medido nas vistas do
    próprio ajuste é otimista por construção.
20. Numa delas, meça com trena da **lente** ao plano do tabuleiro e anote o
    nome do arquivo.
21. Aba **4 · Validar** → aponte a calibração e a pasta nova, preencha a
    distância e o arquivo → **Validar**.

Esperado:

- reprojeção independente: mediana < 0,5 px
- retidão após corrigir a distorção: mediana < 0,5 px
- distância PnP vs. trena: dentro de ~2%

---

## Limites do que isso produz

Vale **só** para esta webcam, em 3840×2160, com este foco e esta exposição, e
**em ar**. Mudar a resolução no software já invalida os intrínsecos. A correção
refrativa do tanque é etapa posterior — esta calibração é a condição de
controle *pinhole* do Experimento 3.
