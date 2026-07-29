# Parecer de auditoria — treino CornerNet-UW (execução de 14/07/2026)

**Auditor:** agente de análise (autor do HANDOFF) · **Método:** verificação independente dos artefatos, não confiança no relatório.

## Veredicto: EXECUÇÃO CONFORME. Resultado científico: parcial, honesto e útil.

---

## 1. Conformidade com o contrato (HANDOFF)

| Item | Verificação | Resultado |
| :--- | :--- | :--- |
| GATE 1 (GPU) | RTX 4070 Ti 12 GB reportada; tempos (~0,17 s/step) compatíveis com GPU, não CPU (~0,8 s) | ✔ |
| GATE 2 (colapso) | Logs da tentativa 1 conferidos: val 138–158 px, hit 0%, loss→0,0018 por ~13 épocas | ✔ plano B justificado |
| Plano B = única alteração | `train.py` (lado Windows) diff: só a loss ponderada, com comentário | ✔ |
| Partição intocada | `dataset.py`: TEST/VAL idênticos; `index.jsonl`: 5.526 linhas | ✔ |
| `eval_vs_opencv.py` intocado | Conferido linha a linha | ✔ |
| Logs preservados | `tentativa1_mse_colapso/` completa (log, stdout, 2 ckpts carregáveis) | ✔ |
| Retreino do zero após plano B | `train_log.csv` reinicia em step 25 com loss 0,231 (nível de inicialização) | ✔ |
| Relatório honesto | Critério 1 marcado como NÃO atingido; critério 2 como parcial — régua não foi movida | ✔ |

**Reprodução independente:** refiz as colunas OpenCV do eval em ambiente separado (mesma semente): as 4 linhas batem exatamente (100%/0,64 · 63%/0,97 · 19,5%/1,16 · 5,5%/1,44). Isso valida o protocolo inteiro de avaliação. As colunas da rede não pude reexecutar (cache local corrompeu minha leitura do `best.pt` — limitação do meu ambiente, não do executor; o formato de save foi validado nos checkpoints da tentativa 1) — aceitas com base na reprodução exata da metade verificável e na consistência interna log↔relatório↔eval.

**Consistência train_log ↔ relatório:** best em step 3220 = 14,785 px / 67,8% ✔; final = 16,931 px / 49,7% ✔; 140 steps/época ✔ (4.494/32).

## 2. Leitura científica dos resultados

**O resultado central é real e importa para H₁:** sob degradação média/severa, a rede mantém taxa de detecção onde o clássico colapsa (66% vs 19,5%; 30% vs 5,5%). É a primeira evidência quantitativa própria (não da literatura) de que o detector profundo agrega robustez no *seu* aparato.

**As ressalvas são igualmente reais:**

1. **Localização degrada forte** (20,5 px no médio vs 1,16 px do OpenCV quando este detecta). A rede "acha" o marcador mas não os cantos com precisão de pose. Para PnP, 20 px é inutilizável; o valor atual da rede é como *fallback de detecção*, não de pose.
2. **Critério 1 não atingido** (14,8 px ≫ 2 px). Nota do auditor contra mim mesmo: a métrica `val_err_px` que defini é média sem gating de confiança — misturas de acertos subpixel com falhas grosseiras. O hit3px de 67,8% mostra que 2/3 dos frames têm os 4 cantos < 3 px. Métrica a corrigir na próxima rodada (mediana + taxa, com gating), sem retroagir o veredicto desta.
3. **Instabilidade entre épocas** (hit3px oscila 26–73%): LR fixo 3e-4 sem scheduler. Esperado; não é bug.
4. **Degradação é sintética.** Nada aqui substitui água turva real com NTU medido (Exp. 1 do delineamento).
5. Sobre o GATE 2: a evidência comparativa sustenta o colapso (tentativa 1 presa em 130+ px no step 1950; tentativa 2 já em ~28–55 px no mesmo ponto), embora a tentativa 1 tenha sido abortada e não se possa provar que nunca escaparia. Decisão correta dado o contrato.

## 3. Recomendações (próxima iteração, em ordem de valor)

1. **RefineNet subpixel** (segundo estágio do Deep ChArUco): crop 64×64 no pico de cada heatmap + regressão fina — ataca diretamente o problema nº 1 (20 px → alvo < 2 px).
2. Métricas de validação corrigidas: mediana, taxa de detecção (conf > 0,3) e hit3px gated.
3. Scheduler (cosine, warmup curto) + ~60 épocas — custo ~40 min na 4070 Ti.
4. Comparar com **DeepArUco++ pré-treinado** (WP3a-ii do plano) antes de investir mais na rede própria — decisão *build vs buy* com medição.
5. Registrar este resultado como baseline v1 congelada (não sobrescrever `best.pt`; renomear para `best_v1_step3220.pt`).

## 4. Situação no plano de pesquisa

WP0 ✔ (baseline clássica) · WP3a parcialmente iniciado (detector profundo v1 treinado e avaliado; falta subpixel e comparação com pré-treinados) · Bloqueios inalterados: CAD (PVNet/sintético) e GT eletromecânico (métrica em mm, WP1).
