# Relatório de execução V2 — RefineNet-UW (estágio 2)

- **Data/hora início e fim:**
  - Início (congelamento v1): 14/07/2026 ~12:13
  - Tentativa A (`--lr 1e-3`, default): 12:13:20 → interrompida ~12:16 (GATE A)
  - Tentativa B (`--lr 3e-3`, correção autorizada): 12:16:59 → interrompida ~12:21 (GATE A falhou de novo → **PARE**)
  - Fim (relatório): 14/07/2026 ~12:22

- **GPU e versões:**
  - GPU: NVIDIA GeForce RTX 4070 Ti
  - Python 3.11.15 · torch 2.13.0+cu126 · CUDA 12.6 · opencv 5.0.0
  - Ambiente: `.venv` existente da v1 (sem deps extras)

- **Comandos exatamente executados:**
  ```bat
  cd C:\Users\Rhayron\Projects\pose\treino_fiducial
  copy best.pt best_v1_step3220.pt
  copy train_log.csv train_log_v1.csv
  .venv\Scripts\python.exe train_refine.py --data data --epochs 20 --batch 256 > run_refine_stdout.txt 2>&1
  ```
  GATE A falhou → arquivamento em `tentativa_refine_lr1e3/` + retreino:
  ```bat
  .venv\Scripts\python.exe train_refine.py --data data --epochs 20 --batch 256 --lr 3e-3 > run_refine_stdout.txt 2>&1
  ```
  GATE A falhou de novo → **PARE** (sem `eval_pipeline2`, sem DeepArUco). Arquivo em `tentativa_refine_lr3e3/`.

- **Batch efetivo e desvios:**
  - Batch **256** (sem OOM).
  - Desvio 1: `--lr 3e-3` na tentativa B (única correção autorizada pelo handoff após falha do GATE A).
  - Desvio 2: treinos **não completaram 20 épocas** — parada deliberada pelo GATE A (época 3).
  - Estágio 1 (`best.pt`) **não** retreinado; cópia congelada em `best_v1_step3220.pt`.
  - Seed, MAX_OFF, partição: inalterados.

- **GATE 1 / CUDA:** implícito OK (device=cuda, RTX 4070 Ti).

- **GATE A (época 3, mediana < 6 px):** **FALHOU** nas duas tentativas.

  | Tentativa | LR | mediana época 3 | GATE A |
  | :--- | ---: | ---: | :--- |
  | A (`tentativa_refine_lr1e3/`) | 1e-3 | **8,64 px** | falhou |
  | B (`tentativa_refine_lr3e3/`, raiz atual) | 3e-3 | **9,10 px** | falhou → PARE |

  Referência do handoff: preditor-zero ~8,7 px. Em ambos os casos a época 3 ainda está na região do zero-predictor.

- **GATE B (reprodutibilidade eval2):** **não executado** (parada obrigatória antes do eval).

- **Época do refine_best.pt (parcial, tentativa B, sem validade de critério):**
  - Melhor mediana observada antes do stop: **2,05 px** no step **767** (época ~12) — *informativo apenas*; treino interrompido por protocolo, não por convergência final.
  - Critério 1 (mediana < 1,5 e &lt;2 px ≥ 80%) **não avaliado** no fim de 20 épocas.

- **Tabela eval_pipeline2:** não gerada (`eval2_result.txt` ausente).

- **Critérios de sucesso: 1 [ ] 2 [ ] 3 [ ]**
  - Nenhum critério de §3 pôde ser marcado: o protocolo mandou parar no GATE A antes de completar treino e eval.
  - DeepArUco++ (§4 opcional): **não executado** (não bloqueante; prioridade foi o reporte do GATE A).

- **Anomalias, decisões e por quê:**
  1. **GATE A falhou, mas o modelo aprendia depois da época 3.** Nas duas tentativas a mediana caiu de forma clara após a janela do gate:
     - lr 1e-3: época 3 = 8,64 → época 9 = **3,12** (e ~2–3 px em curso)
     - lr 3e-3: época 3 = 9,10 → época 9 = **2,30** → época 12 = **2,05**
     Interpretação cautelosa (sem chutar hiperparâmetro): o warmup de 200 steps + ~60 steps/época implica que a época 3 ainda está no fim do warmup / início do cosine — a régua “&lt; 6 px na época 3” pode ser cedo demais para este schedule, não evidência de colapso. **Não retreinamos** com outras LRs/épocas: handoff proíbe além da correção `3e-3`.
  2. Logs/pesos de ambas tentativas **preservados** em subpastas; raiz contém o estado da tentativa B no momento do stop (`refine_log.csv`, `run_refine_stdout.txt`, `refine_best.pt`, `refine_ckpt.pt`).
  3. Nenhum aviso crítico de CUDA/OOM; s/step ~0,09–0,10 (treino) / ~0,60 (val).

- **Tempo de treino e s/step:**
  - Tentativa A: ~3 min (abort ~época 10–11)
  - Tentativa B: ~4 min (abort ~época 12)
  - s/step médio treino: ~0,09–0,10 s

## Checklist

- [x] v1 congelada (`best_v1_step3220.pt`, `train_log_v1.csv`)
- [x] GATE A avaliado na época 3
- [x] Correção autorizada `--lr 3e-3` tentada e arquivada a tentativa anterior
- [x] Segunda falha do GATE A → **PARE e reporte** (sem retreino extra, sem eval formal)
- [ ] 20 épocas completas — **não** (parada por gate)
- [ ] `eval_pipeline2.py` — **não**
- [x] Artefatos de treino + relatório presentes; tentativas em subpastas
- [x] Estágio 1 intacto; partição/labels/vídeos intocados

## Artefatos

| Artefato | Estado |
| :--- | :--- |
| `best_v1_step3220.pt`, `train_log_v1.csv` | congelados |
| `best.pt` | inalterado (estágio 1) |
| `refine_log.csv`, `run_refine_stdout.txt` | tentativa B (parcial, lr 3e-3) |
| `refine_best.pt`, `refine_ckpt.pt` | tentativa B no stop (best med 2,05 px @ step 767) |
| `tentativa_refine_lr1e3/` | tentativa A completa do abort |
| `tentativa_refine_lr3e3/` | cópia da tentativa B no abort |
| `eval2_result.txt` | **ausente** (não rodado) |
| `RELATORIO_EXECUCAO_V2.md` | este arquivo |

## Mensagem para o auditor / próximo passo sugerido (sem executar)

O refinador **não colapsou** no sentido da v1; o aprendizado só se manifesta **depois** da época 3. Para a próxima rodada (se autorizada), candidatos a decisão *a priori* (não testados aqui):

1. Relaxar GATE A para época 6–8 (onde ambos os LRs já passaram de 6 px), ou
2. Reduzir warmup / aumentar LR máximo de forma justificada, ou
3. Completar 20 épocas com o schedule atual e só então avaliar o pipeline 2 estágios.

Qualquer uma dessas exige **novo handoff** com régua fixada antes de rodar.
