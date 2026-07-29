# O que já é implementável com os dados atuais

**Data:** 14/07/2026 · **Base:** medições feitas nesta análise (não suposições), sobre os 13 vídeos de 27/05 e as 12 aquisições `.m2k`.

---

## 1. Caracterização dos insumos (medido)

**Vídeos (13):** 1920×1080 @ ~60 fps, 7,6–18,8 s cada. Câmera **fora do tanque** filmando através da parede de vidro (interfaces ar–vidro–água → caso refrativo do delineamento, H₂).

**Ultrassom (12 × `.m2k`, formato M2M/Gekko):** FMC completo — 64 disparos × 64 elementos, amostragem 125 MHz, PRF 3633 Hz, filtro 2,5–7,5 MHz. **Aquisição indexada por tempo (16 s), sem eixo de encoder** — as varreduras são freehand e os nomes casam com os vídeos (charuto claro/escuro × trajetória linear/isométrica × 3 repetições). Cada arquivo tem ~295 MB de RF bruto (`acq_data.bin`) + descritores XML legíveis.

**Marcadores (detectado empiricamente):** braçadeira com ArUco **DICT_7X7, ID 0** (lateral) + marcador **DICT_5X5, ID 3** (topo); há marcadores menores colados no próprio tubo. O aparato mistura dicionários — isso precisa ser documentado/confirmado com quem montou.

## 2. Baseline WP0 — já executada (resultado real)

Detector ArUco clássico (OpenCV 5.0), 1 frame a cada 15, todos os 13 vídeos:

| Resultado | Valor |
| :--- | :--- |
| Taxa de detecção (12 de 13 vídeos) | **98–100%** |
| Vídeo 20260527_164606 (menor nitidez: 920 vs ~2700) | **60%** |
| Marcadores por frame detectados | 1 (só o ID 0 grande; os menores escapam ao detector clássico) |
| PnP (smoke test, intrínsecos nominais) | 100% de convergência, 0 falhas em 126 poses |
| Jitter mediano entre amostras | ~7,5–11,4 mm nominais (não métrico) |

Arquivos: `baseline_aruco_wp0.csv` (tabela completa por vídeo) e `deteccao_exemplo.png` (overlay de verificação).

**Leitura científica dos números:**
- Em água limpa e boa iluminação, o detector clássico **não é o gargalo** — a taxa é ~100%. A justificativa do Deep ChArUco/DeepArUco++ passa a depender de degradação (turbidez, escuro, blur), que é exatamente o que os experimentos 1–2 vão variar. O vídeo de menor nitidez já mostra a queda (100% → 60%): o fenômeno existe e é mensurável no seu tanque.
- Os **marcadores pequenos não são detectados** pelo detector clássico nem com parâmetros ajustados — primeiro caso de uso real para o detector profundo, e um problema de aparato (tamanho/ângulo dos marcadores) a discutir.
- A amplitude anômala em Z no smoke test é consistente com o erro refrativo esperado sem calibração — evidência preliminar a favor da motivação de H₂ (não conclusiva; requer Exp. 3).

## 3. Implementável AGORA (sem ground truth, sem calibração)

| # | Item | WP | Bloqueio? |
| :--- | :--- | :--- | :--- |
| 1 | Repositório + estrutura + testes de geometria "ouro" (Pose, PnP, métricas contra soluções analíticas) | WP0 | Nenhum |
| 2 | Pipeline de ingestão vídeo→frames→catálogo (feito em protótipo nesta análise; falta versionar) | WP0 | Nenhum |
| 3 | Baseline ChArUco/ArUco clássica completa + EDA (nitidez, blur, reflexos) — **parcialmente feita aqui** | WP0 | Nenhum |
| 4 | **Calibração intrínseca da câmera em ar** (tabuleiro ChArUco impresso, ~30 vistas) — destrava pose métrica | WP1 | Só requer a câmera |
| 5 | Leitor `.m2k` (XML já parseado; falta decodificar layout do `acq_data.bin`) + reconstrução TFM das 12 aquisições — o lab provavelmente já tem ferramentas M2M/CIVA | Fase 2 | Confirmar layout binário |
| 6 | Dados sintéticos (BlenderProc + CAD da braçadeira) — pose exata por construção | WP2b | Requer o CAD |
| 7 | CycleGAN sim2real usando os frames reais de 27/05 como domínio-alvo (~12k frames disponíveis) | WP2c | Depende do item 6 |
| 8 | **Treinamento exploratório do detector fiducial profundo**: os frames reais onde o OpenCV detecta com sucesso geram pseudo-labels de cantos automaticamente (~12k amostras); fine-tuning de DeepArUco++/ChArUcoNet para recuperar os frames que o clássico perde e os marcadores pequenos | WP3a | Nenhum — é o treinamento exploratório mais barato e honesto disponível |
| 9 | Filtro temporal / suavização de trajetória sobre as poses PnP (protótipo da fusão) | WP3c | Nenhum |

## 4. Ainda BLOQUEADO (e por quê)

| Item | Bloqueio real |
| :--- | :--- |
| Pose métrica (mm/graus) | Sem calibração intrínseca + refrativa da configuração câmera–vidro–tanque |
| Avaliação de acurácia de qualquer modelo | Sem ground truth eletromecânico sincronizado (WP1) |
| Treino do PVNet com pose 6DoF real | Sem GT e sem CAD renderizável (dá para começar pelo sintético, item 6) |
| Registro espacial 3D validado (Exp. 6) | Sem GT + sem transformação braçadeira→marcador→plano da imagem US medida |
| Sincronização vídeo↔ultrassom | Vídeos e `.m2k` têm relógios independentes; sem evento comum (LED/batida) só há alinhamento grosseiro por duração (~16 s) |

## 5. Riscos de aparato detectados nos dados (levar à próxima sessão de tanque)

1. **Um único marcador grande visível por frame** → pose de 4 pontos coplanares: fraca em orientação e ambígua em profundidade. Adicionar tabuleiro ChArUco (como já previsto no delineamento) ou ≥3 marcadores maiores em faces distintas da braçadeira.
2. **Dicionários misturados (7×7 e 5×5)** sem documentação da geometria relativa — medir e registrar a transformação entre marcadores e o referencial do transdutor.
3. **Nitidez cai ~4× ao longo da sessão** (2715 → 684) — causa a identificar (turbidez crescente? iluminação? foco?). Registrar NTU por sessão, como o plano já exige.
4. **Sem evento de sincronização** vídeo↔scanner — implementar LED visível no quadro disparado pelo trigger de aquisição (já previsto no WP1.5).
5. Reflexos da parede de vidro e a mão do operador ocluindo o marcador aparecem nos frames — úteis como oclusão natural, mas precisam ser catalogados.

## 6. Sequência recomendada (2–3 semanas, ordem de dependência)

1. Repositório + testes de geometria (item 1) — o instrumento de medida antes do fenômeno.
2. Formalizar a baseline desta análise dentro do repositório (itens 2–3), com todos os frames (aqui foi 1/15).
3. Calibrar a câmera em ar (item 4) e repetir o PnP → primeira trajetória em escala aproximada.
4. Pseudo-labels + fine-tuning exploratório do detector profundo (item 8) — primeiro treinamento de DL do projeto, comparável contra a baseline já medida.
5. Em paralelo: obter CAD da braçadeira (item 6) e confirmar com o lab o leitor `.m2k` (item 5).

---

*Gerado a partir de medições reproduzíveis: script da baseline e CSV acompanham este relatório. Nenhum número deste documento foi estimado sem medição, exceto onde marcado como "nominal".*
