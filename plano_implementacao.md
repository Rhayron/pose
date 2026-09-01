# Plano de Implementação da Pesquisa

## Estimação Visual de Pose 6DoF de Transdutor Ultrassônico e Registro Espacial 3D de Imagens de Ultrassom para Inspeção Subaquática por END

**Mestrando:** Rhayron de Sousa Nogueira — CPGEI/PPGCA, UTFPR / LASSIP
**Data do plano:** 06/07/2026 · **Próximo marco:** reunião de validação em 08/07/2026
**Insumos existentes:** delineamento de pesquisa, survey bibliográfico auditado, 13 vídeos exploratórios + 1 foto do aparato (27/05/2026, sem ground truth sincronizado), GPU local para treinamento.

---

## 0. Princípios norteadores

Este plano operacionaliza o delineamento em pacotes de trabalho (WPs) executáveis, cada um com **entradas, saídas, critérios de aceitação mensuráveis e vínculo explícito às hipóteses H₁–H₄**. Três princípios são inegociáveis:

1. **Método científico, não chute.** Nenhum componente entra no pipeline final sem baseline medido antes e depois. Toda decisão de projeto (arquitetura, hiperparâmetro, pré-processamento) é registrada com a evidência que a motivou. Resultados negativos são documentados — eles delimitam o envelope operacional, que é resultado da dissertação.
2. **Reprodutibilidade por construção.** Sementes fixas, versionamento de dados e de código, configuração declarativa, ambientes congelados. Qualquer figura da dissertação deve ser regenerável por um único comando a partir de dados versionados.
3. **O ground truth eletromecânico é sagrado.** Todo o edifício experimental repousa na cadeia de calibração (Exp. 0). Erro sistemático ali contamina tudo; por isso o WP de calibração precede e bloqueia os demais, e seu orçamento de erro (*error budget*) é pré-requisito formal para iniciar aquisições com GT.

---

## 1. Arquitetura de software

### 1.1. Stack tecnológica

| Camada | Escolha | Justificativa |
| :--- | :--- | :--- |
| Linguagem | Python ≥ 3.11 | Ecossistema dominante em CV/DL; type hints maduros |
| DL framework | PyTorch ≥ 2.x (+ Lightning) | Padrão nas implementações de referência (PVNet, DeepArUco++); Lightning isola loop de treino do código científico |
| Visão clássica | OpenCV ≥ 4.x (contrib) | ChArUco/ArUco, calibração, PnP/RANSAC |
| Geometria 3D | Open3D + SciPy Rotation | Registro 3D, transformações SO(3), visualização |
| Renderização sintética | Blender + BlenderProc2 | Renderização foto-realista com pose conhecida por construção; saída no formato BOP |
| Configuração | Hydra + YAML | Cada experimento é um arquivo de config versionado — elimina "flags mágicas" |
| Rastreamento de experimentos | MLflow (local) ou Weights & Biases | Registro automático de métricas, hiperparâmetros, artefatos e commit hash |
| Versionamento de dados | DVC (remote em disco externo/NAS do lab) | Dados de tanque e sintéticos versionados junto ao código, sem inflar o git |
| Qualidade de código | ruff (lint+format), mypy, pytest, pre-commit | Barreira automática de qualidade antes de cada commit |
| CI | GitHub Actions (lint + testes unitários em CPU) | Impede regressão silenciosa nos módulos geométricos |
| Ambiente | conda/uv + `environment.lock` + Dockerfile (CUDA) | Congela o ambiente de treino; Docker garante portabilidade p/ servidor futuro |

### 1.2. Estrutura do repositório (monorepo)

```
pose6dof-uw/
├── pyproject.toml            # metadados, deps, ruff, mypy, pytest
├── environment.yml / uv.lock
├── Dockerfile                # imagem CUDA p/ treino reprodutível
├── dvc.yaml                  # pipeline de dados (estágios declarativos)
├── configs/                  # Hydra
│   ├── calib/                # intrínseca, refrativa, hand-eye
│   ├── dataset/              # real, sintético, misturas (H₃)
│   ├── model/                # pvnet.yaml, deep_charuco.yaml
│   ├── fusion/               # estratégias de fusão (H₁)
│   └── experiment/           # exp0.yaml ... exp6.yaml (1 config = 1 experimento)
├── src/pose6dof/
│   ├── calib/                # calibração intrínseca, refrativa, hand-eye
│   │   ├── intrinsics.py
│   │   ├── refractive.py     # modelo flat-port: ray-tracing ar–vidro–água
│   │   └── hand_eye.py       # AX=XB + fechamento de cadeia de referenciais
│   ├── data/
│   │   ├── ingest.py         # extração de frames de vídeo, EXIF, sincronização
│   │   ├── datasets.py       # Dataset PyTorch (formato BOP)
│   │   ├── synthetic/        # scripts BlenderProc + domain randomization
│   │   ├── sim2real/         # CycleGAN/Mask-CycleGAN (H₃)
│   │   └── splits.py         # partição por trajetória/sessão (anti-vazamento)
│   ├── enhance/              # realce de imagem (opcional, variável de ablação)
│   ├── models/
│   │   ├── pvnet/            # backbone, cabeças de vetores, votação RANSAC
│   │   ├── charuco_net/      # detecção + refinamento subpixel
│   │   └── losses.py
│   ├── pose/
│   │   ├── pnp.py            # EPnP/SQPnP + RANSAC; variante refrativa
│   │   ├── fusion.py         # seleção/média ponderada por incerteza/filtro (H₁)
│   │   └── uncertainty.py    # propagação de covariância da pose
│   ├── registration/         # Fase 2
│   │   ├── transform.py      # imagem US → referencial da peça
│   │   └── compose.py        # composição volumétrica + export (PLY/VTK)
│   ├── eval/
│   │   ├── metrics.py        # erro transl./rot. geodésico, ADD/ADD-S, reproj.
│   │   ├── stats.py          # testes pareados, tamanho de efeito, IC bootstrap
│   │   └── report.py         # geração automática de tabelas/figuras
│   └── viz/                  # overlays de pose, curvas NTU×erro, render 3D
├── scripts/                  # entrypoints finos (CLI via Hydra) — sem lógica
├── tests/
│   ├── unit/                 # geometria com poses sintéticas exatas (ouro)
│   └── integration/          # pipeline curto em mini-dataset versionado
├── notebooks/                # exploração APENAS; nada de lógica de produção
└── docs/                     # decisões de projeto (ADRs), protocolo de aquisição
```

### 1.3. Boas práticas obrigatórias

- **Testes de geometria como fundação.** Módulos de transformação rígida, PnP, projeção refrativa e métricas têm testes unitários contra soluções analíticas (pose sintética conhecida → projeção → recuperação → erro < 1e-6). É o único jeito de confiar nas medições experimentais: *o instrumento de medida é testado antes do fenômeno.*
- **Convenção única de referenciais**, documentada em `docs/frames.md`: `T_ab` = transformação que leva coordenadas do frame `b` para o frame `a`; frames nomeados (`cam`, `marker`, `probe`, `piece`, `scanner`). Toda função que recebe/retorna pose usa dataclass `Pose(R: Rotation, t: np.ndarray, frame_from, frame_to)` com verificação de compatibilidade — elimina a classe de bug mais comum (e mais silenciosa) em pipelines de pose.
- **1 experimento = 1 config Hydra + 1 commit + 1 run no MLflow.** Proibido treinar com working tree sujo (hook que registra `git diff` e bloqueia).
- **Dados imutáveis.** Aquisições brutas nunca são editadas; derivados (frames, crops, labels) são estágios DVC regeneráveis.
- **Sementes e determinismo**: `torch.use_deterministic_algorithms(True)` onde viável; sementes registradas por run; variância entre sementes reportada (mín. 3 sementes nos experimentos comparativos).
- **ADRs (Architecture Decision Records)** curtos em `docs/adr/` para cada decisão relevante — vira material direto para o capítulo de metodologia.

---

## 2. Pacotes de trabalho (WPs)

Dependências: WP0 → WP1 → {WP2, WP3 em paralelo} → WP4 → WP5 → WP6.

### WP0 — Bootstrap e exploração dos dados existentes (1–2 semanas) ⚡ *antes de 08/07 se possível*

Aproveita os 13 vídeos exploratórios de 27/05 **sem esperar por GT**: eles servem para caracterizar o problema e construir a baseline mais barata possível.

| Tarefa | Saída | Critério de aceitação |
| :--- | :--- | :--- |
| Repositório + CI + pre-commit + estrutura §1.2 | repo funcional | CI verde; `pytest` roda; lint limpo |
| Ingestão dos vídeos (`data/ingest.py`): extração de frames, metadados, catálogo | catálogo CSV/parquet por vídeo (resolução, fps, duração, condições) | 13 vídeos catalogados e versionados via DVC |
| **Baseline ChArUco clássico (OpenCV)** nos frames extraídos | taxa de detecção por vídeo/frame; poses PnP (sem calibração refrativa ainda) | curva de taxa de detecção documentada — este número é a referência que todo o resto deve superar |
| EDA visual: histogramas de nitidez/contraste, motion blur, reflexos do tanque, cobertura de poses | relatório `docs/eda_videos_2705.md` | lista objetiva de problemas do aparato p/ discutir na reunião de 08/07 |
| Testes unitários de geometria (Pose, PnP, métricas) | suíte "ouro" | 100% dos testes analíticos passando |

**Valor científico imediato:** a baseline OpenCV nos vídeos reais responde empiricamente "quão ruim é o detector clássico no *nosso* tanque?" — hoje isso é suposição da literatura, não medição própria.

### WP1 — Calibração e cadeia de referenciais (Exp. 0; 3–6 semanas)

O elemento metodologicamente crítico. Nada de aquisição com GT antes de fechar este WP.

1. **Calibração intrínseca em ar** (padrão ChArUco; ≥ 30 vistas; erro de reprojeção alvo < 0,3 px).
2. **Calibração refrativa** (câmera no ar, parede do tanque, alvo na água): ray-tracing ar–parede–água com `d_cam`, espessura e índice **medidos**; avaliar a ferramenta de Seegräber et al. (2025) antes de implementar do zero (*build vs. buy* — ADR). Não tratar como *flat port* de *housing*. Comparar contra pinhole+distorção em ar como controle (insumo direto de H₂/Exp. 3).
3. **Calibração mão-olho** (`AX = XB`): transformação scanner↔câmera↔peça; medir **erro de fechamento de cadeia** repetindo a calibração em N sessões.
4. **Orçamento de erro da referência**: documento formal com incerteza de cada elo (encoder, hand-eye, refração residual). *Toda comparação futura será interpretada contra este orçamento — diferenças menores que o erro da referência não são evidência.*
5. **Sincronização temporal** câmera ↔ scanner: definir mecanismo (trigger de hardware, LED de sincronismo visível no quadro, ou timestamp comum) e medir a latência residual.

**Critério de aceitação:** erro de fechamento e erro de reprojeção sob a água quantificados, com repetibilidade entre sessões; documento de orçamento de erro aprovado pelo orientador.

### WP2 — Construção do conjunto de dados (6–10 semanas, paralelizável com WP3)

**2a. Protocolo de aquisição real** (`docs/protocolo_aquisicao.md`, escrito ANTES da primeira sessão):
- Matriz experimental: trajetórias × distâncias × ângulos × iluminação × turbidez (NTU medido por turbidímetro, degraus repetíveis com agente dosado) × oclusão (% de cobertura por anteparo padronizado).
- Cada sessão gera um manifesto (YAML): condições físicas, NTU medido, configuração de iluminação, operador, hash dos arquivos.
- Formato de anotação: **BOP** (padrão da comunidade de pose 6D) — permite usar toolkits de avaliação existentes e publicar o dataset como contribuição secundária.
- Partição treino/val/teste **por trajetória e por sessão** (nunca por frame) — anti-vazamento, verificado por teste automatizado em `splits.py`.

**2b. Dados sintéticos:** modelo CAD do conjunto transdutor/braçadeira no BlenderProc; domain randomization (pose, iluminação, texturas de fundo, parâmetros de câmera); simulação física de efeitos subaquáticos (atenuação espectral, véu de espalhamento dependente de distância, partículas); pose exata por construção.

**2c. Adaptação de domínio (H₃):** CycleGAN/Mask-CycleGAN sintético→real usando frames reais NÃO anotados (os vídeos de 27/05 já servem como domínio-alvo!). Validação da adaptação por métricas de distribuição (FID) *e* pelo efeito downstream no erro de pose — nunca só pela aparência visual.

**Critério de aceitação:** ≥ N sessões reais com GT cobrindo a matriz (N a fixar com orientador); dataset sintético ≥ 50k imagens; relatório de qualidade da adaptação de domínio.

### WP3 — Módulos de estimação de pose (6–10 semanas)

**3a. Módulo fiducial profundo (estilo Deep ChArUco).**
- Ordem de ataque: (i) baseline OpenCV já medida no WP0; (ii) avaliar pesos/código públicos de DeepArUco++; (iii) fine-tuning com dados sintéticos + reais do tanque; (iv) refinamento subpixel.
- Decisão informada por dados: se (ii) já satisfizer o requisito no nosso domínio, o esforço de (iii) é redirecionado — registrado em ADR com as medições.

**3b. Módulo de keypoints densos (estilo PVNet).**
- Seleção de K keypoints 3D no CAD por farthest-point sampling; treinar predição de campos vetoriais + segmentação; votação RANSAC; PnP.
- Começar do código de referência público do PVNet, modernizando backbone se necessário (medir antes/depois).
- Treino: mixed precision, checkpointing, early stopping por métrica de pose (não por loss), tudo dimensionado para a GPU local (ver §4).

**3c. Fusão (H₁).**
- Implementar em ordem de complexidade crescente, medindo cada degrau: (1) seleção por confiança (fallback), (2) média ponderada por covariância, (3) filtro temporal (EKF em SE(3)) — parar no nível em que o ganho marginal deixar de ser significativo (Occam experimental).
- Cada fonte de pose reporta incerteza (covariância via jacobiano do PnP; confiança da rede calibrada por temperature scaling).

**Critério de aceitação:** cada módulo avaliado isoladamente no conjunto de validação real com as métricas da §3 do delineamento; fusão superando ambos em pelo menos um regime de degradação.

### WP4 — Registro espacial 3D (Fase 2; 3–5 semanas)

- `registration/transform.py`: composição `T_piece_img = T_piece_probe(t) · T_probe_img` com a geometria do plano de imagem do US; interpolação temporal da pose para o instante de cada disparo.
- Composição volumétrica em grade regular sobre o CAD da peça (Open3D); exportação PLY/VTK para inspeção.
- Avaliação com descontinuidades conhecidas (entalhes/furos usinados): erro de posicionamento (mm) sob pose visual vs. sob pose eletromecânica — **o mesmo código de registro roda com as duas fontes de pose**, isolando a variável de interesse (H₄).

### WP5 — Campanha experimental e análise estatística (6–10 semanas)

Executa Exps. 1–6 do delineamento, cada um como config Hydra própria:

| Exp | Hipótese | Variável independente | Análise |
| :--- | :--- | :--- | :--- |
| 1 | H₁ | turbidez (NTU) | curvas de degradação; comparação pareada por frame/trajetória |
| 2 | H₁ | oclusão (%) | idem |
| 3 | H₂ | modelo refrativo vs. pinhole | teste pareado (Wilcoxon), tamanho de efeito, IC bootstrap |
| 4 | H₃ | composição do treino | curvas erro × quantidade de dados reais |
| 5 | H₁ | estratégia (isolado × fusão) | envelope turbidez×oclusão; ADD/ADD-S; tempo de inferência |
| 6 | H₄/H₀ | fonte de pose no registro | erro de posicionamento de defeitos conhecidos (mm) |

Regras estatísticas (em `eval/stats.py`, aplicadas uniformemente): desenho pareado sempre que possível; relato de mediana + IQR + IC 95% bootstrap; tamanho de efeito junto ao valor-p; correção para múltiplas comparações; ≥ 3 sementes nos treinos comparados. **Diferenças dentro do orçamento de erro da referência (WP1) não são reivindicadas como resultado.**

Ablações transversais (calibração refrativa, realce, sintético, fusão) rodam como variações da mesma config — o custo marginal é só computação.

### WP6 — Consolidação, artigo e dissertação (contínuo; pico ao final)

- `eval/report.py` regenera todas as tabelas e figuras a partir dos runs do MLflow — a dissertação nunca contém número digitado à mão.
- Artigo submetido assim que Exps. 1–5 fecharem (prioridade do orientador), com repositório e dataset (se autorizado) como material suplementar.
- Auditoria bibliográfica final: verificação individual de DOI/autoria/ano de toda referência (conforme nota de integridade do delineamento) — checklist rastreável em `docs/refs_audit.md`.

---

## 3. Uso imediato dos vídeos de 27/05 (sem GT)

Mesmo exploratórios, os vídeos têm quatro usos concretos já neste mês:

1. **Baseline ChArUco clássico** — o número de referência do projeto (WP0).
2. **Domínio-alvo para sim2real** — frames reais não anotados alimentam o CycleGAN (WP2c).
3. **Caracterização do aparato** — reflexos nas paredes do tanque, iluminação, motion blur típico do movimento manual → lista de correções do setup antes das aquisições com GT (evita queimar sessões caras com problemas evitáveis).
4. **Teste de fumaça do pipeline de ingestão** — todo o caminho vídeo→frames→detecção→pose→visualização roda de ponta a ponta antes de existir dado "valioso".

---

## 4. Dimensionamento para GPU local

- PVNet-like em resolução ~640×480: cabe em GPU de 8–12 GB com batch 8–16 e mixed precision (AMP); com 6 GB, usar gradient accumulation. Tempo estimado de treino por experimento: horas a poucos dias — compatível com as ~10 configurações comparativas do WP5 se agendadas com fila simples.
- CycleGAN é o item mais pesado: treinar em resolução reduzida (256–286 px) e aplicar em patches, como na literatura de referência.
- Mitigações se a GPU local saturar: (i) reduzir resolução de entrada com medição do impacto; (ii) congelar backbone pré-treinado; (iii) Docker pronto (§1.1) permite migrar para servidor/nuvem sem retrabalho.
- Registrar consumo (tempo, VRAM) por run no MLflow — o custo computacional entra no relato de viabilidade prática.

---

## 5. Cronograma integrado (ajustar com orientador em 08/07)

| Mês | WPs ativos | Marco |
| :--- | :--- | :--- |
| Jul/2026 | WP0, início WP1 | Reunião 08/07: EDA dos vídeos + baseline OpenCV + este plano |
| Ago–Set/2026 | WP1; WP2b (sintético) em paralelo | Orçamento de erro da referência aprovado |
| Set–Nov/2026 | WP2a (aquisições com GT), WP2c, WP3a/3b | Dataset v1 congelado; módulos com resultados preliminares |
| Nov/2026–Jan/2027 | WP3c (fusão), WP5 (Exps. 1–5) | Resultados de pose consolidados → **iniciar artigo** |
| Jan–Fev/2027 | WP4, WP5 (Exp. 6) | Registro 3D validado (H₄) |
| Fev–Abr/2027 | WP6 | Submissão do artigo; redação da dissertação |

---

## 6. Riscos de implementação (complementares aos do delineamento)

| Risco | Sinal precoce | Mitigação |
| :--- | :--- | :--- |
| Cadeia de referenciais mal fechada | erro de fechamento não repetível entre sessões (WP1) | não avançar para WP2a; revisar fixação mecânica e protocolo |
| Código de referência (PVNet) defasado/incompatível | falha ao reproduzir resultados publicados em dataset padrão (LINEMOD) | validar reprodução ANTES de adaptar ao domínio próprio |
| Sincronização câmera–scanner imprecisa | erro de pose correlacionado com velocidade do movimento | LED de sincronismo no quadro; trajetórias com paradas |
| GPU local insuficiente p/ campanha do WP5 | fila de treinos > 1 semana | migração via Docker p/ servidor/nuvem (decisão já preparada) |
| Vazamento treino/teste inflando resultados | teste automatizado de partição falhando | bloqueio no CI; partição por sessão sempre |
| Dataset real menor que o planejado | atraso nas sessões de tanque | sintético+adaptação assume papel maior (H₃ vira mitigação, além de hipótese) |

---

## 7. Definition of Done da dissertação (rastreável)

- [ ] Orçamento de erro da referência publicado e citado em toda comparação (WP1)
- [ ] Dataset real+sintético versionado, com manifestos e partições auditáveis (WP2)
- [ ] H₁–H₄ cada uma com experimento, estatística pareada e tamanho de efeito reportados (WP5)
- [ ] Registro 3D com erro de posicionamento de defeitos conhecidos quantificado vs. referência (WP4/Exp. 6)
- [ ] Toda figura/tabela regenerável por comando único a partir de runs versionados (WP6)
- [ ] 100% das referências auditadas contra DOI/fonte original (WP6)
- [ ] Artigo submetido antes da redação final (prioridade do orientador)
