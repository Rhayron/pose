# Parecer de auditoria V2 — RefineNet subpixel (execução de 14/07/2026)

**Auditor:** agente de análise (autor do HANDOFF_V2) · **Método:** verificação dos logs + reavaliação independente dos pesos + experimentos de auditoria em CPU.

## Veredicto

**Execução: CONFORME e exemplar** — o executor parou no GATE A como mandava o protocolo, arquivou tudo, não moveu a régua e reportou com precisão (todos os números conferidos contra os logs brutos e contra recálculo independente dos pesos).

**Projeto do experimento: DUAS FALHAS DE MINHA AUTORIA**, ambas detectadas pela auditoria. O resultado líquido, porém, é uma boa notícia inesperada sobre a v1.

## 1. Verificações

| Checagem | Resultado |
| :--- | :--- |
| Logs ↔ relatório (épocas 3/9/12, ambas tentativas) | Batem exatamente |
| `refine_best.pt` (step 767, mediana 2,05 px) | Recalculado por mim em 435 patches: 1,98 px / <2 px 50,8% ✔ |
| v1 congelada, partição/labels/estágio 1 intocados | ✔ |
| Tentativas arquivadas, sem retreino não autorizado | ✔ |
| GATE B / eval2 | Corretamente NÃO executado (parada obrigatória) — coberto pela auditoria abaixo |

## 2. Falha de projeto nº 1 (minha): GATE A media o modelo durante o warmup

Com batch 256 há 59 passos/época; o warmup de 200 passos termina na época 3,4 — exatamente onde fixei o gate. As duas tentativas estavam na região do preditor-zero na época 3 e **aprendendo normalmente depois** (lr 3e-3: 9,1 → 2,3 px na época 9; 2,05 na 12, ainda caindo no stop forçado). Não houve colapso; houve régua mal posicionada. O executor agiu certo em obedecê-la e parar.

## 3. Falha de projeto nº 2 (minha, mais importante): a premissa do refinador era falsa

Rodei o pipeline de 2 estágios em CPU (estágio 1 = `best_v1_step3220.pt`; n=60 do teste, mesma semente do protocolo). Por canto detectado:

| Nível | Estágio 1: mediana | Estágio 1: P90 | Estágio 1: >5 px | Refinado: mediana |
| :--- | ---: | ---: | ---: | ---: |
| leve | 0,87 px | 1,75 px | 3% | 2,95 px |
| médio | 0,99 px | 2,16 px | 5% | 2,59–2,83 px |
| severo | 1,10 px | 3,54 px | 9% | 3,67 px |

Três conclusões:

1. **Os "20 px" da auditoria v1 eram artefato da métrica média.** A mediana do estágio 1 é ~1 px mesmo sob degradação — a média era inflada por 3–9% de cantos catastróficos (mediana dos outliers: ~90 px — a rede escolhe um pico errado, ex.: reflexo ou outro canto).
2. **O refinador piora o caso típico** (erro intrínseco ~2 px sobre estimativas que já estão em ~1 px) **e não pode corrigir os outliers** (90 px ≫ alcance de ±12 px, por construção). Verificado diretamente: nos cantos onde o estágio 1 errou >5 px, o refinador manteve ~93 px.
3. Teste de Occam (`cornerSubPix` clássico sobre os picos): ajuda só no nível leve (0,87→0,55 px), piora no médio/severo. Os picos do estágio 1 já são quase ótimos dado o borrão.

**Implicação positiva para a dissertação:** a v1 é melhor do que a auditoria v1 sugeria. Onde detecta, localiza com mediana ~1 px — utilizável para PnP — e detecta 100/70/28% sob leve/médio/severo onde o OpenCV faz 68/23/7% (n=60). O problema real e único é rejeitar os 3–9% de picos catastróficos.

## 4. Disposição dos artefatos v2

`refine_best.pt` fica arquivado como registro (não integrar ao pipeline). Resultado negativo documentado — delimita o que não funciona e por quê, e vale relato na dissertação (metodologia: métrica média vs mediana; risco de projetar solução sobre diagnóstico enviesado).

## 5. Próximo passo correto (v3) — sem GPU, sem retreino

O problema restante é **seleção de picos**, não regressão: rejeição de outliers por consistência geométrica — extrair top-K candidatos por canal de heatmap e escolher a combinação consistente com um quadrilátero projetivamente plausível (homografia de quadrado; ou simplesmente validar com o decode do ArUco na região). É pós-processamento puro em CPU: **posso desenvolver e avaliar eu mesmo, sem handoff**, contra a mesma régua (mediana, P90, taxa >5 px, por nível). Ganhos esperados: derrubar os 3–9% de catastróficos sem tocar no caso típico de ~1 px.

Lições registradas do ciclo v2: gates devem ser posicionados em função do schedule (época ≠ tempo de aprendizado); diagnósticos que motivam arquitetura nova exigem distribuição do erro (mediana/P90/outliers), nunca só a média.
