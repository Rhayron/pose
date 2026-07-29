# HANDOFF V2 — Refinamento subpixel (estágio 2) + avaliação do pipeline completo

**Para:** agente executor (GPU local) · **De:** agente de análise/auditoria (14/07/2026)
**Contexto:** a auditoria da v1 (`AUDITORIA.md`) mostrou que o CornerNet detecta onde o
OpenCV falha (66% vs 19,5% no nível médio), mas localiza mal sob degradação (20–25 px).
Este handoff ataca exatamente isso com um segundo estágio subpixel (estilo RefineNet
do Deep ChArUco). Regras do jogo idênticas: método científico, régua fixa, logs preservados.

## 0. Congelamento da v1 (OBRIGATÓRIO, antes de tudo)

```bat
cd C:\Users\Rhayron\Projects\pose\treino_fiducial
copy best.pt best_v1_step3220.pt
copy train_log.csv train_log_v1.csv
```

`best.pt` continua sendo usado como estágio 1 (não retreinar o CornerNet nesta rodada —
uma variável por vez: a única novidade é o refinador).

## 1. Novos arquivos (já validados em CPU pelo agente de análise)

| Arquivo | Papel |
| :--- | :--- |
| `refine_dataset.py` | patches 64×64 on-the-fly dos crops existentes; offset GT subpixel; MESMA degradação e MESMA partição por vídeo |
| `refine_model.py` | RefineNet-UW, ~435k parâmetros, regressão (dx,dy) |
| `train_refine.py` | cosine+warmup, métricas gated (mediana, <1 px, <2 px), save atômico, log próprio (`refine_log.csv`) |
| `eval_pipeline2.py` | avaliação 2 estágios, mesmo protocolo/semente do eval v1 (linhas cv e g_taxa devem REPRODUZIR a tabela v1) |

Smoke test CPU já feito: loss 0,565→0,381 em 100 passos (preditor-zero estagnaria em ~0,49);
dataset = 15.356 patches de treino / 1.740 val. Loop, resume e métricas validados.

## 2. Execução

```bat
.venv\Scripts\activate
python train_refine.py --data data --epochs 20 --batch 256 > run_refine_stdout.txt 2>&1
python eval_pipeline2.py --data data --coarse best.pt --refine refine_best.pt > eval2_result.txt 2>&1
```

- **Execução única, sem dividir em blocos** — o scheduler cosine usa o total de passos;
  rodar em pedaços com `--max-steps` deforma o LR (artefato observado no smoke de CPU).
- ~1.200 passos; estimativa < 15 min na 4070 Ti. Sem OOM esperado (batch 256 @ 64×64).
- Não alterar seed, lr, MAX_OFF, partição, nem o `best.pt` do estágio 1.

**GATE A (época 3):** `val mediana` deve estar **< 6 px** (o preditor-zero fica em ~8,7 px,
que é a mediana do offset uniforme ±12 px — abaixo disso há aprendizado real). Se não:
única correção autorizada = `--lr 3e-3`, retreino do zero, tentativa anterior arquivada
em `tentativa_refine_lr1e3/`. Se ainda falhar: PARE e reporte.

**GATE B (sanidade de reprodutibilidade):** em `eval2_result.txt`, as colunas `cv_taxa`
e `g_taxa` devem bater com a tabela v1 (`eval_result.txt`): 100/63/19,5/5,5% e
100/100/66/30%. Divergência = erro de ambiente/protocolo; PARE e reporte antes de
interpretar qualquer número do refinador.

## 3. Critérios de sucesso (fixados ANTES da execução)

1. **Validação:** mediana < 1,5 px e <2 px ≥ 80% (patches, res do crop 384).
2. **Pipeline completo (`eval2_result.txt`):** `r_med` ≤ 3 px nos níveis `leve` e `medio`
   (v1 grosso: 11 e 20,5 px de média) sem queda de `g_taxa`.
3. **Estiramento (não obrigatório):** `r_med` < 2 px no `leve` — paridade com OpenCV onde ele opera.

Resultado abaixo do critério é resultado: reportar como está.

## 4. Etapa opcional (se sobrar tempo): baseline DeepArUco++ pré-treinado

Decisão *build vs buy* do plano (WP3a-ii). Repo verificado: https://github.com/AVAuco/deeparuco
(Python 3.9, modelos pré-treinados inclusos, licença AGPL-3.0 — ok para comparação
acadêmica; anotar a licença se algum código for incorporado). Rodar o `demo.py` deles
sobre ~50 crops de teste degradados (níveis medio/severo) e reportar taxa de detecção
para comparação qualitativa com nossa rede. Em ambiente separado (`venv` próprio, py3.9)
para não poluir o ambiente do treino. Se der atrito de dependências > 30 min, abandonar
e registrar — não é bloqueante.

## 5. Artefatos obrigatórios para auditoria

`refine_log.csv`, `run_refine_stdout.txt`, `eval2_result.txt`, `refine_best.pt`,
`refine_ckpt.pt`, `best_v1_step3220.pt` (congelado), e `RELATORIO_EXECUCAO_V2.md`
(mesmo modelo do relatório v1: ambiente, comandos, gates, desvios, critérios marcados,
anomalias, tempos). Tentativas descartadas em subpastas, nunca apagadas.

## 6. Proibições

As mesmas do HANDOFF v1 (partição, vídeos de teste, labels intocados; sem deps extras
no ambiente principal; logs preservados) + não retreinar/alterar o estágio 1 nesta rodada.
