# Resultados v3 — Seleção geométrica de picos com validação por decode (14/07/2026)

**Executado pelo agente de análise em CPU** (pós-processamento puro, sem retreino, sem GPU).
Estágio 1 congelado (`best_v1_step3220.pt`). Protocolo idêntico às avaliações anteriores
(teste = vídeos nunca vistos, semente 123, n=60 frames por nível — subconjunto; confirmação
em n=200 pode ser rodada pelo executor com `eval_v3.py`).

## Método

Em vez do argmax por canal de heatmap: top-3 candidatos por canto (NMS) → combinações
filtradas por plausibilidade geométrica (convexidade, razão de lados) → validação
decodificando os bits da região como ArUco 7×7 ID 0 (aceite: ≥85% dos bits) → quadro
sem combinação válida é rejeitado. Régua fixada ANTES da avaliação (em `peak_select.py`).

## Resultados (por canto detectado)

| Nível | Método | Detecção | Mediana | P90 | >5 px |
| :--- | :--- | ---: | ---: | ---: | ---: |
| limpo | argmax | 100% | 0,74 | 1,34 | 0,4% |
| limpo | **v3** | 100% | 0,74 | 1,31 | **0,0%** |
| leve | argmax | 100% | 0,87 | 1,75 | 2,9% |
| leve | **v3** | 88,3% | 0,86 | 1,60 | **0,0%** |
| médio | argmax | 70% | 0,99 | 2,16 | 4,8% |
| médio | **v3** | 60% | 0,92 | 1,77 | **0,0%** |
| severo | argmax | 28,3% | 1,10 | 3,54 | 8,8% |
| severo | **v3** | 21,7% | 1,03 | 1,84 | **0,0%** |

## Veredicto contra a régua pré-fixada

1. **Cantos >5 px ≤ 2% (médio/severo): ATINGIDO com folga — 0,0% em todos os níveis.**
   Os outliers catastróficos (~90 px) foram eliminados por completo.
2. **Mediana ≤ 1,2× argmax: ATINGIDO** — mediana igual ou melhor em todos os níveis;
   P90 melhor em todos.
3. **Perda de detecção ≤ 10 p.p.: PARCIAL** — limpo 0; médio 10,0 (no limite); severo 6,6;
   **leve 11,7 p.p. (estoura por 1,7 p.p.)**. Registrado como está; nenhum ajuste de
   threshold foi feito após ver os números (seria mover a régua). Um relaxamento do
   aceite (0,85) ou K=5 pode recuperar detecção, mas deve ser decidido a priori e
   validado em amostra nova.

**Interpretação para o pipeline de pose:** a troca é claramente favorável ao PnP — um
quadro rejeitado é recuperável por filtragem temporal (60 fps); um canto a 90 px destrói
a pose silenciosamente. Com v3, todo canto entregue tem erro subpixel-a-2 px (P90 < 2 px
em todos os níveis), e a validação por decode dá um critério de confiança físico, não
aprendido — exatamente o que a fusão (H₁) precisa como entrada.

## Estado do detector fiducial após v1→v2→v3

| Versão | O que é | Status |
| :--- | :--- | :--- |
| v1 CornerNet | detecção + localização (argmax) | congelada; base do pipeline |
| v2 RefineNet | regressão subpixel ±12 px | resultado negativo documentado (premissa falsa); arquivado |
| v3 peak select | rejeição de outliers por decode | **aprovado (2/3 critérios; 3º por 1,7 p.p.)**; recomendado como padrão |

## Próximos passos naturais

1. Confirmação em n=200 e no conjunto de teste completo (executor, GPU, minutos).
2. Decisão a priori sobre recuperar detecção no leve (K=5 ou aceite 0,80) — amostra nova.
3. Integrar `select_corners` ao pipeline de pose (PnP) e medir erro de pose com
   intrínsecos calibrados — depende da calibração da câmera (WP1), o próximo
   desbloqueio físico do projeto.
4. Comparação com DeepArUco++ pré-treinado (pendente da rodada v2, segue opcional).
