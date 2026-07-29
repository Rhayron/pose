# Treino exploratório — detector fiducial profundo (estilo Deep ChArUco/DeepArUco)

Pacote pronto para rodar na **sua GPU local**. O pipeline foi validado ponta a ponta
em CPU (sandbox) em 14/07/2026 — ver `analise_implementavel_agora.md` e o smoke test abaixo.

## O que este treino é (e o que não é)

- **É**: um detector profundo de cantos do marcador ArUco 7×7 (ID 0) da braçadeira,
  treinado com **pseudo-labels** (detecções do OpenCV em frames limpos, 3.906 frames)
  e **degradação sintética** subaquática (escuridão, blur, véu de backscatter, ruído) —
  a mesma estratégia do DeepArUco. O objetivo mensurável: manter detecção onde o
  clássico falha (vídeo escuro caiu para 60% na baseline).
- **Não é**: o experimento final da dissertação. Sem GT eletromecânico, o teto de
  acurácia é a própria pseudo-label. Serve para H₁ preliminar e para dominar o stack.

## Setup (Windows, uma vez)

```
cd C:\Users\Rhayron\Projects\pose\treino_fiducial
python -m venv .venv && .venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cu126
pip install opencv-contrib-python numpy
```

## Passos

```
# 1. Gerar labels (se ainda não existirem em data/labels_all.jsonl — já incluído)
# 2. Extrair crops dos vídeos (~5 min, ~4.700 crops + negativos, ~200 MB)
python make_crops.py --videos ..\videos --labels data\labels_all.jsonl --out data\crops

# 3. Treinar (GPU 6-12 GB: batch 32; ~15-40 min para 30 épocas)
python train.py --data data --epochs 30 --batch 32

# 4. Avaliar contra o OpenCV clássico sob degradação (vídeos de teste nunca vistos)
python eval_vs_opencv.py --data data --weights best.pt
```

## Decisões de projeto (com justificativa)

| Decisão | Justificativa |
| :--- | :--- |
| Partição por vídeo: teste = 164606 + 170626, val = 165049 | Anti-vazamento (plano §WP2a); teste inclui o vídeo onde o clássico falha |
| Heatmaps gaussianos (σ=2) dos 4 cantos, MSE | Formulação do Deep ChArUco/DeepArUco; simples e estável |
| Degradação sintética em treino | Pseudo-labels só existem onde o clássico acerta; a degradação cria os casos difíceis com label conhecida (aluno supera professor) |
| Rede compacta (~1,9 M par., U-Net 4 níveis) | Cabe em qualquer GPU; tempo real (>30 fps) viável; medir antes de crescer |
| Negativos (20%) | Rede precisa reportar "sem marcador" (conf. < 0,3) para a fusão futura |

## Smoke test executado (CPU sandbox, 14/07/2026)

125 passos, batch 8, res 128: loss 0,239 → 0,181; erro de canto na validação
79,3 → 66,9 px, queda monotônica. Loop, checkpoint/resume e avaliação validados.
Convergência real requer a GPU (30 épocas ≈ 4.200 passos a batch 32).

**Risco conhecido:** MSE em heatmaps esparsos pode colapsar para zero. Se o erro
de val estagnar após ~5 épocas com heatmaps quase nulos, trocar por MSE ponderado
(peso ~50 nos pixels > 0,1) ou focal loss — decidir pelos logs, não por palpite.

## Critérios de sucesso deste exploratório

1. `eval_vs_opencv.py`: taxa de detecção da rede **superior à do OpenCV** nos níveis
   médio/severo, com erro de canto < 3 px onde ambos detectam.
2. Erro de validação < 2 px (resolução 256) — paridade com a pseudo-label.
3. Registrar tudo (log CSV + checkpoint) para comparação futura com DeepArUco++ pré-treinado.

## E o PVNet?

**Ainda não treinável** — faltam dois insumos que nenhum código substitui:

1. **Modelo CAD da braçadeira/transdutor** → define os keypoints 3D (FPS) e permite
   gerar dados sintéticos com pose exata (BlenderProc). *Pedir ao Kalid.*
2. **Pose 6DoF de referência por frame** → GT eletromecânico sincronizado (WP1) ou
   rota 100% sintética enquanto o GT não existe.

Com o CAD em mãos, a rota imediata é: renderização BlenderProc (50k imagens, formato
BOP) + adaptação de domínio usando os 12k frames reais destes vídeos como domínio-alvo
(H₃). O treino do PVNet aí é padrão. Sem CAD, qualquer treino seria chute — contra o
princípio do projeto.
