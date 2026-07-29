# Calibração intrínseca — webcam_pc

**Data:** 2026-07-29T13:47:01-03:00 · **Resolução:** 3840x2160 · **Vistas:** 9 · **Semente:** 123
**Escala métrica:** quadrado = 34 mm (fonte: **medido**)

## Intrínsecos

| Parâmetro | Valor | IC 95% (bootstrap sobre vistas) |
| :--- | ---: | :--- |
| fx | 2899.281 | [1842.57, 3625.09] |
| fy | 2912.689 | [1848.45, 3612.44] |
| cx | 1876.019 | [1806.78, 1911.54] |
| cy | 786.679 | [551.25, 900.17] |

Modelo de distorção escolhido: **k1k2k3_tang** · coeficientes: `[0.114075, -0.40965, -0.004469, -0.004116, 0.337008]`
FOV: 67.0° x 40.4° · razão de aspecto do pixel: 1.00462

## Seleção do modelo (erro em vistas retidas)

| Modelo | coef. | mediana (px) | P90 (px) | >1 px |
| :--- | ---: | ---: | ---: | ---: |
| k1k2 | 2 | 0.636 | 1.614 | 25.6% |
| k1k2_tang | 4 | 0.647 | 1.623 | 28.4% |
| **k1k2k3_tang** | 5 | 0.561 | 1.213 | 18.2% |
| racional | 8 | 0.561 | 1.190 | 17.2% |

Protocolo: 20 partições aleatórias 70/30, vence o modelo mais simples dentro de 0.02 px do melhor.

## Erro de reprojeção (ajuste completo)

RMS global 0.6124 px · mediana 0.430 · P90 0.963 · P99 1.586 · máx 2.480 · 6.02% dos cantos acima de 1 px

Vistas suspeitas (erro mediano atípico): nenhuma

## Veredicto contra a régua pré-registrada

| Critério | Medido | Resultado |
| :--- | :--- | :--- |
| n_vistas_min | 9 >= 25 | **REPROVADO** |
| cobertura_completa | views 9/25; inclinadas 4/8; muito inclinadas 0/5; escala medio 0/4; escala grande 0/4 | **REPROVADO** |
| rms_global_px_max | 0.6124 <= 0.5 | **REPROVADO** |
| p90_erro_canto_px_max | 0.9625 <= 1.0 | APROVADO |
| erro_mediano_holdout_px_max | 0.5613 <= 0.6 | APROVADO |
| largura_relativa_ic95_fx_max | 61.48% <= 2% | **REPROVADO** |

Diagnósticos (informativos, não reprovam):

- assimetria_fx_fy = 0.0046 (referência 0.02)
- desvio_cx = 0.0115 (referência 0.1)
- desvio_cy = 0.1358 (referência 0.1)

**Situação: REPROVADA — recapturar, não relaxar o critério**

## Limites de validade

- Válida SOMENTE para esta câmera, em 3840x2160, com os mesmos ajustes de
  foco/exposição/zoom registrados em `sessao_captura` neste arquivo. Qualquer mudança
  (inclusive trocar a resolução do software) invalida fx, fy, cx, cy.
- Calibração **em ar**. Não descreve o caminho ar–vidro–água do tanque: aplicá-la
  submersa produz erro sistemático — que é justamente o que H₂ se propõe a medir.
  Esta calibração é a condição de controle (pinhole) do Experimento 3.