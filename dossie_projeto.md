# Dossiê do projeto — pose

Estimação visual de pose 6DoF de um transdutor ultrassônico e registro
espacial 3D de imagens de ultrassom para inspeção subaquática por END.

Mestrando: Rhayron de Sousa Nogueira · CPGEI/PPGCA, UTFPR · LASSIP.
Documento consolidado em 2026-09-02, a partir do estado real do repositório.
Fontes: `HANDOFF.md`, `delineamento_pesquisa_mestrado.md`,
`plano_implementacao.md`, `roteiro_experimentos.md`, relatórios de
`treino_fiducial/` e sessões de `aquisicao/`.

## 1. A pesquisa em um parágrafo

Métodos de reconstrução de ultrassom (S-scan, TFM, CPWC) pressupõem amostragem
em posição espacial conhecida: movimento não registrado entre transdutor e
peça desfoca ou desloca a imagem reconstruída. A pesquisa propõe rastrear
visualmente a pose 6DoF do transdutor — marcador fiducial na braçadeira,
câmera externa ao tanque — e usar essa pose para posicionar espacialmente as
imagens de US em inspeção subaquática freehand, onde encoder e braço mecânico
não alcançam. As hipóteses centrais: detector fiducial profundo supera o
clássico sob degradação (turbidez, oclusão, blur); modelagem refrativa
melhora a pose através da interface ar–vidro–água; dados sintéticos adaptados
reduzem a necessidade de dados reais anotados; e a pose visual sustenta um
registro 3D com erro compatível com o de referência eletromecânica.

## 2. Quadro geral — da aquisição de pose ao entregável final

O pipeline completo, com o corte honesto entre o que está em execução AGORA e
o que é Fase 2:

```
AGORA (campanha atual)
  [1] Aquisição sincronizada
      vídeo 4K (S600, K selado) + .m2k (Multi2000, FMC/PRF 3633 Hz)
      sync por clique + batidas + stop-and-go        → E0, E1, E4
        |
  [2] Detecção do marcador
      ArUco clássico (baseline) / detector v1+v3     → E2, E6
        |
  [3] Pose por quadro
      PnP com K de ar; reprojeção, jitter estático,
      desambiguação temporal de flips                → E3
        |
  [4] Pose ↔ US no tempo comum
      offset + deriva estimados; pose interpolada
      por disparo, com incerteza declarada           → E5  ← MARCO

FASE 2 (pré-requisitos adiados por decisão)
  [5] Calibração refrativa (ar–vidro–água)  → pose métrica em mm
  [6] Mão-olho + GT eletromecânico          → orçamento de erro da referência
  [7] Registro espacial 3D                  → US posicionado na peça (H4)
  [8] Campanha de degradação                → turbidez × oclusão (H1)

ENTREGÁVEIS FINAIS
  [9] Artigo (Exps. 1–5 do delineamento) → dissertação → dataset público
      (formato BOP, se autorizado) + código reprodutível
```

O marco [4] é o ponto de prova do delineamento: pipeline de ponta a ponta
rodando com dado real, antes de qualquer investimento em refração e GT. Tudo
que se mede agora (pixels, taxas, repetibilidade) transfere para a Fase 2;
nada precisa ser refeito quando a escala métrica entrar.

## 3. Estado atual (medido, não estimado)

| Frente | Estado | Evidência |
| :--- | :--- | :--- |
| Intrínseca 4K em ar | fechada | RMSE 0,599 px, 30 quadros, Caliscope 0.11.3; perfil selado `s600.json`, transferência validada |
| Baseline ArUco (WP0) | medida | 98–100% de detecção em água limpa (12/13 vídeos); 60% no vídeo de baixa nitidez; marcadores pequenos invisíveis ao clássico |
| Detector fiducial profundo | treinado | v1 congelada + seleção v3: P90 < 2 px e 0% de cantos > 5 px em todos os níveis de degradação; v2 arquivada como resultado negativo documentado |
| Aquisição sincronizada | operacional | `gravar.py`: pré-roll real, carimbo monotônico por quadro, fila de 600 quadros, JSON de sessão com qualidade de sincronismo declarada |
| Smoke take 4K | executado | sessão 20260901_165544_983: modo 4K abriu, 0 descartes, foco constante em 356.0 |
| Refrativa / mão-olho / GT | adiados | decisão registrada no HANDOFF; nenhum número em mm é reivindicado até lá |

## 4. Problemas vivos e correções aplicadas

Autofoco — CORRIGIDO (2026-09-02). O driver DirectShow da S600 responde à
trava com a flag CameraControl_Flags (1 = automático, 2 = manual); o código
comparava o readback com o valor pedido (0) e declarava falha exatamente
quando a trava funcionava — o foco ficou constante em 356.0 por 74 amostras
na sessão de smoke. Três camadas de correção: interpretação correta da flag +
fixação do foco absoluto no valor corrente; prova funcional de estabilidade
(o PREPARAR só chega a PRONTO após observar o foco constante com a cena real
na frente da câmera, e foco instável agora é ERRO, não aviso); e foco de
referência selado em sidecar (`s600.foco.json`, 356.0) com proveniência
explícita — o valor foi observado na mesma bancada um dia após a calibração,
não lido durante ela, e o arquivo declara isso.

FPS — EM ABERTO (E0.2). O smoke mediu 20,79 fps contra 30 nominal, com zero
descartes de fila: a câmera entrega menos quadros. Hipótese: autoexposição
ativa (readback não observável) alonga o shutter em luz fraca; o período de
48 ms é consistente com shutter de ~1/21 s. Correção esperada: mais luz na
cena — recupera fps e reduz motion blur pela mesma causa. Decisão pendente de
medição em três níveis de iluminação antes da campanha.

## 5. Roteiro de experimentos (síntese; detalhe em roteiro_experimentos.md)

Premissa: sem refração. Todas as métricas são internas — nenhuma converte
pixel em milímetro.

| Exp | O quê | Critério-chave |
| :--- | :--- | :--- |
| E0 | Saúde do aparato: gate de foco, fps × iluminação, latência de pipeline | fps ≥ 28 no nível escolhido, ou aceite documentado de ~21 |
| E1 | Campanha: 2 trajetórias × 2 velocidades × 3 repetições, ritual com batidas e paradas | ≥ 12 takes válidos; 0 descartes; marcador visível ≥ 90% |
| E2 | Detecção no domínio 4K: baseline vs v1+v3; pendências do v3 (n=200, nível leve) | profundo ≥ baseline nos degradados; P90 de consenso < 2 px |
| E3 | Pose PnP: reprojeção, convergência, jitter nas paradas, flips do IPPE | reprojeção mediana < 1 px; jitter estático quantificado sem GT |
| E4 | Sincronização por métodos redundantes: clique, batidas, stop-and-go, relógio | concordância batidas × stop-and-go dentro de 1 quadro |
| E5 | Pose interpolada por disparo do US, incerteza propagada — o MARCO | pipeline de ponta a ponta em um comando por take |
| E6 | (opcional) fine-tuning 4K com pseudo-labels, se E2 mostrar gap | régua definida antes de treinar |

A jogada central do protocolo: as paradas deliberadas (stop-and-go) servem
simultaneamente à sincronização (E4) e à medição de repetibilidade estática
da pose sem ground truth (E3). Um ritual, dois experimentos.

## 6. Sincronização pose ↔ ultrassom (síntese)

| # | Método | Nível | Custo | Quando |
| :--- | :--- | :--- | :--- | :--- |
| S1 | Clique global no START | grosseira | zero (implementado) | agora |
| S2 | 3 batidas da sonda na peça, início e fim: correlação entre desaceleração da pose e transiente no RF | ~1 quadro + deriva | zero | agora |
| S3 | Stop-and-go: correlação dos perfis movimento/parado (pose × decorrelação de A-scans) | ~1 quadro + deriva contínua | zero | agora |
| S4 | Relógio comum do PC (timestamp no XML do .m2k, a confirmar) | ~1 s (prior) | um parsing | agora |
| S5 | LED no campo de visão acionado pelo trigger do Multi2000; interpolação sub-quadro já implementada (--roi) | fina (~ms) | LED + acesso ao trigger | próximo upgrade |
| S6 | Trigger → microcontrolador: LED + log serial por disparo | fina, por A-scan | moderado | Fase 2 |

Recomendação: rodar S1+S2+S3+S4 juntos na campanha (redundância de custo
zero, validação por concordância); S5 quando o conector de trigger for
identificado; S6 quando o registro exigir pose por A-scan.

## 7. Riscos principais

| Risco | Sinal precoce | Mitigação |
| :--- | :--- | :--- |
| fps baixo persistir mesmo com luz | E0.2 reprova nos três níveis | aceitar ~21 fps documentado; blur medido entra como covariável |
| Detector não transferir para 4K/água | E2.2 abaixo da baseline | E6 (fine-tuning com pseudo-labels do próprio domínio) |
| Ambiguidade de pose do marcador único | taxa de flips alta em E3 | desambiguação temporal; médio prazo: mais marcadores/ChArUco na braçadeira |
| Batidas invisíveis no RF | correlação sem pico em E4.2 | S3 segura o take; ajustar força/local da batida no ritual |
| Latência variável do software do US | offsets de início e fim divergem além da deriva | reportar por take; upgrade S5 elimina a dependência do clique |

## 8. Entregável final da pesquisa

A cadeia completa termina em três artefatos, na ordem de prioridade do
orientador: artigo submetido assim que os experimentos comparativos fecharem;
dissertação com toda figura e tabela regenerável por comando a partir de runs
versionados; e, se autorizado, dataset público no formato BOP com manifestos
de condição por sessão. O critério de pronto da dissertação (registrado no
plano de implementação): orçamento de erro da referência publicado e citado em
toda comparação; hipóteses H1–H4 cada uma com experimento, estatística pareada
e tamanho de efeito; registro 3D com erro de posicionamento de defeitos
conhecidos quantificado contra a referência; 100% das referências auditadas.

O roteiro atual (E0–E6) constrói o alicerce disso: aquisição confiável,
detecção validada no domínio real, pose com precisão interna medida e
sincronização triangulada — tudo o que a Fase 2 consome sem retrabalho.
