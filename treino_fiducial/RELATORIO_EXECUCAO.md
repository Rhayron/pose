# Relatório de execução — treino CornerNet-UW

- **Data/hora início e fim:**
  - Início (setup + GATE 1): 14/07/2026 ~11:03
  - Tentativa 1 (MSE puro, abortada por colapso): 11:05:46 → ~11:14:45
  - Tentativa 2 (plano B, MSE ponderado, 30 épocas): 11:14:50 → 11:34:14
  - Eval vs OpenCV: 11:34:19 → 11:34:46
  - Fim (relatório): 14/07/2026 ~11:36

- **GPU (modelo, VRAM) e versões (torch, cuda, opencv, python):**
  - GPU: NVIDIA GeForce RTX 4070 Ti, 12,0 GiB VRAM
  - Python: 3.11.15
  - torch: 2.13.0+cu126
  - CUDA (torch): 12.6
  - opencv-contrib-python: 5.0.0
  - numpy: 2.4.6

- **Comandos exatamente executados:**
  ```bat
  cd C:\Users\Rhayron\Projects\pose\treino_fiducial
  python -m venv .venv
  .venv\Scripts\pip install --upgrade pip
  .venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu126
  .venv\Scripts\pip install opencv-contrib-python numpy
  .venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
  del ckpt.pt best.pt train_log.csv
  .venv\Scripts\python.exe train.py --data data --epochs 30 --batch 32 > run_stdout.txt 2>&1
  ```
  Após GATE 2 (colapso), arquivamento + plano B + retreino:
  ```bat
  mkdir tentativa1_mse_colapso
  copy train_log.csv,run_stdout.txt,ckpt.pt,best.pt tentativa1_mse_colapso\
  del ckpt.pt best.pt train_log.csv
  ```
  Alteração autorizada em `train.py` (loss → MSE ponderado), depois:
  ```bat
  .venv\Scripts\python.exe train.py --data data --epochs 30 --batch 32 > run_stdout.txt 2>&1
  .venv\Scripts\python.exe eval_vs_opencv.py --data data --weights best.pt > eval_result.txt 2>&1
  ```

- **Batch efetivo e qualquer desvio do handoff (com justificativa):**
  - Batch efetivo: **32** (sem OOM na 4070 Ti 12 GB).
  - Único desvio de código: plano B do GATE 2 (ver abaixo). Seed, lr, res e partição inalterados.
  - Logs da tentativa 1 preservados em `tentativa1_mse_colapso/` (proibição §6: não apagar logs intermediários).

- **GATE 1 (cuda):** **OK** — `torch.cuda.is_available() == True`, device `NVIDIA GeForce RTX 4070 Ti`.

- **GATE 2 (colapso):** **plano B aplicado** após a tentativa 1.
  - Sintomas na tentativa 1 (~épocas 5–12): `val_err_px` estagnado ~130–158 px (nunca < 40), `val_hit3px` sempre 0,0%, loss < 0,01 (chegou a ~0,0019) — colapso clássico do MSE em heatmaps esparsos.
  - Treino interrompido; pesos/logs arquivados; loss em `train.py` trocada para MSE ponderado:
    ```python
    w = 1.0 + 49.0 * (hm > 0.1).float()
    loss = ((torch.sigmoid(model(x)) - hm) ** 2 * w).mean()
    ```
  - Retreino do zero (sem resume). Comentário no código registra a justificativa.

- **Época do best.pt, val_err_px, val_hit3px:**
  - `best.pt`: step **3220** (época ~22/30), **val_err_px = 14,785**, **val_hit3px = 0,6782 (67,8%)**
  - Final (época 29): val_err_px = 16,93, val_hit3px = 49,7%
  - Melhor hit3px observado: 73,1% na época 26 (val_err 14,84 px) — best.pt salva por menor erro médio, não por hit.

- **Tabela do eval_vs_opencv (colar saída):**
  ```
  amostras de teste: 200
  nivel     cv_taxa  cv_err  net_taxa  net_err
  limpo      100.0%    0.64    100.0%     1.43
  leve        63.0%    0.97    100.0%    11.02
  medio       19.5%    1.16     66.0%    20.52
  severo       5.5%    1.44     30.0%    24.46
  ```

- **Critérios de sucesso: 1 [ ] 2 [parcial] 3 [x]**
  1. **Não atingido.** Melhor `val_err_px` = 14,78 px (meta: < 2 px, ou tendência com < 5 px). Houve queda clara 150 → ~15 px, mas o erro final/best permanece bem acima de 5 px.
  2. **Parcial.** Taxa de detecção da rede **≥ OpenCV** em `medio` (66% ≥ 19,5%) e `severo` (30% ≥ 5,5%) — e também em `leve` (100% ≥ 63%). Porém o erro médio da rede onde detecta é **>> 3 px** (medio 20,5; severo 24,5). Em `limpo`, a rede localiza bem (1,43 px), mas sob degradação a localização degrada forte.
  3. **Atingido.** Nenhuma modificação em `TEST_VIDEOS`/`VAL_VIDEOS` de `dataset.py`. Teste só via `eval_vs_opencv` no split de teste.

- **Anomalias, warnings, decisões tomadas e por quê:**
  - `ckpt.pt`/`best.pt` iniciais do smoke test de CPU foram apagados antes do treino (handoff: corrompidos por interrupção).
  - Tentativa 1: colapso MSE → interrupção deliberada + plano B (única alteração de código autorizada).
  - Variância alta de `val_hit3px` nas últimas épocas (26–73%), tipicamente alternando com `val_err` — possível sensibilidade a conf. threshold / picos fracos; não investigado além do registro (sem retreino extra).
  - Sem OOM; workers=4 (default) sem falha.
  - Dependências apenas as listadas no handoff.

- **Tempo total de treino e s/step médio:**
  - Tentativa 1 (abortada): ~9 min (~12 épocas).
  - Tentativa 2 (completa, 30 épocas / 4200 steps): **~19,4 min**.
  - s/step médio (após warmup): **~0,16–0,17 s/step** (picos ~0,75–0,80 s em steps de validação/log).
  - Eval: ~27 s.

## Checklist final do executor

- [x] GATE 1 passou (GPU ativa)
- [x] Treino completou 30 épocas (plano B; tentativa 1 parada justificada no GATE 2)
- [x] `eval_vs_opencv.py` rodou sobre `best.pt`
- [x] Artefatos + `RELATORIO_EXECUCAO.md` presentes na pasta
- [x] Nenhuma proibição da §6 violada

## Artefatos na pasta

| Artefato | Notas |
| :--- | :--- |
| `train_log.csv` | log da tentativa 2 (plano B) |
| `run_stdout.txt` | stdout da tentativa 2 |
| `eval_result.txt` | saída bruta do eval |
| `best.pt`, `ckpt.pt` | melhor época e último estado (plano B) |
| `tentativa1_mse_colapso/` | logs/pesos da tentativa 1 (colapso) |
| `train.py` | loss com MSE ponderado (plano B) |
| `RELATORIO_EXECUCAO.md` | este arquivo |
