# HANDOFF — Execução do treino do detector fiducial (CornerNet-UW)

**Para:** agente executor (máquina local do Rhayron, com GPU)
**De:** agente de análise (sessão de 14/07/2026)
**Auditoria:** o agente de análise auditará os artefatos ao final. Este documento define o contrato.

---

## 1. Contexto mínimo

Projeto de mestrado (pose 6DoF de transdutor ultrassônico subaquático, UTFPR/LASSIP).
Este treino é **exploratório** (WP3a do plano): detector profundo de cantos do marcador
ArUco 7×7 ID 0, treinado com pseudo-labels do OpenCV + degradação sintética.
Meta: superar o detector clássico sob degradação. Não é o experimento final da dissertação.

Leia `README.md` antes de executar. Princípio inegociável do projeto: **método
científico, não chute** — nada de alterar hiperparâmetros ou código sem registrar o quê e por quê.

## 2. Estado atual (verificado)

| Item | Estado |
| :--- | :--- |
| `data/labels_all.jsonl` | 3.906 frames rotulados (pseudo-labels OpenCV, subpixel) |
| `data/crops/` + `data/index.jsonl` | 5.526 crops 384×384 (4.494 treino / 506 val / 526 teste, partição POR VÍDEO) |
| `dataset.py`, `model.py`, `train.py`, `eval_vs_opencv.py` | Código completo; loop validado em CPU (125 passos, loss 0,239→0,181) |
| Vídeos-fonte | `..\videos\*.mp4` (13 arquivos, não tocar) |

Se `data/crops/` estiver vazio ou incompleto (deve ter 5.526 jpg), regenere:
`python make_crops.py --videos ..\videos --labels data/labels_all.jsonl --out data/crops`
e confira que `data/index.jsonl` termina com 5.526 linhas.

## 3. Execução (ordem estrita)

```bat
cd C:\Users\Rhayron\Projects\pose\treino_fiducial
python -m venv .venv
.venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cu126
pip install opencv-contrib-python numpy
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

**GATE 1:** se `cuda.is_available()` for `False`, PARE e reporte. Não treine em CPU.

**PASSO OBRIGATÓRIO — limpar resíduos do smoke test de CPU** (o `ckpt.pt` atual está
**corrompido** por uma interrupção; se não apagar, o treino falha ao tentar retomar):

```bat
del ckpt.pt best.pt train_log.csv
```

```bat
python train.py --data data --epochs 30 --batch 32 > run_stdout.txt 2>&1
```

- GPU < 8 GB e der OOM: reduza para `--batch 16` (registre no relatório).
- Não altere `--seed`, `--lr`, `--res` nem a partição em `dataset.py`.
- O treino é retomável: se interromper, rode o mesmo comando de novo (usa `ckpt.pt`).

**GATE 2 (anti-colapso, ~época 5):** abra `train_log.csv`. Se `val_err_px` não caiu
abaixo de ~40 px e a loss estiver < 0,01 com heatmaps nulos (sintoma: `val_hit3px`
sempre 0 e erro estagnado), o MSE colapsou para zero — risco documentado no README.
Correção autorizada (única alteração de código permitida, registre-a):
em `train.py`, troque a linha da loss por MSE ponderado:

```python
w = 1.0 + 49.0 * (hm > 0.1).float()
loss = ((torch.sigmoid(model(x)) - hm) ** 2 * w).mean()
```

Apague `ckpt.pt`, `best.pt` e `train_log.csv` e retreine do zero. Reporte que o plano B foi usado.

```bat
python eval_vs_opencv.py --data data --weights best.pt > eval_result.txt 2>&1
```

## 4. Critérios de sucesso (pré-definidos, não mover a régua)

1. `val_err_px` final < 2 px (res 256) OU tendência claramente decrescente com < 5 px.
2. `eval_vs_opencv.py`: taxa de detecção da rede ≥ à do OpenCV nos níveis `medio` e
   `severo`, com erro médio < 3 px onde ambos detectam.
3. Sem vazamento: nenhuma modificação em `TEST_VIDEOS`/`VAL_VIDEOS` de `dataset.py`.

Resultado que NÃO atinge os critérios também é resultado — reporte-o tal como é.
Não retreine repetidamente "até dar certo" variando coisas sem registro.

## 5. Artefatos obrigatórios para a auditoria

Deixe na pasta `treino_fiducial/` (não apague nada):

| Artefato | Conteúdo |
| :--- | :--- |
| `train_log.csv` | log completo de loss e validação por época |
| `run_stdout.txt`, `eval_result.txt` | saídas brutas de treino e avaliação |
| `best.pt`, `ckpt.pt` | pesos (melhor época e último estado) |
| `RELATORIO_EXECUCAO.md` | ver modelo abaixo — preenchido honestamente |

### Modelo de `RELATORIO_EXECUCAO.md`

```markdown
# Relatório de execução — treino CornerNet-UW
- Data/hora início e fim:
- GPU (modelo, VRAM) e versões (torch, cuda, opencv, python):
- Comandos exatamente executados:
- Batch efetivo e qualquer desvio do handoff (com justificativa):
- GATE 1 (cuda): OK/FALHOU
- GATE 2 (colapso): não ocorreu / plano B aplicado no passo X
- Época do best.pt, val_err_px, val_hit3px:
- Tabela do eval_vs_opencv (colar saída):
- Critérios de sucesso: 1 [ ] 2 [ ] 3 [ ]  (marcar só o que foi atingido)
- Anomalias, warnings, decisões tomadas e por quê:
- Tempo total de treino e s/step médio:
```

## 6. Proibições explícitas

- Não treinar/avaliar com vídeos de teste (`164606`, `170626`) em nenhuma etapa.
- Não editar `labels_all.jsonl`, `index.jsonl` nem os vídeos.
- Não mudar critérios de sucesso, semente ou partição.
- Não apagar logs intermediários, mesmo de tentativas falhas.
- Nenhuma dependência além das listadas (sem wandb/mlflow nesta rodada exploratória).

## 7. Checklist final do executor

- [ ] GATE 1 passou (GPU ativa)
- [ ] Treino completou 30 épocas (ou parada justificada e registrada)
- [ ] `eval_vs_opencv.py` rodou sobre `best.pt`
- [ ] 4 artefatos + `RELATORIO_EXECUCAO.md` presentes na pasta
- [ ] Nenhuma proibição da §6 violada
