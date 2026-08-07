# pose

Estimação visual de pose 6DoF de transdutor ultrassônico e registro espacial 3D
de imagens de ultrassom para inspeção subaquática por END.

Pesquisa de mestrado. O delineamento completo, com hipóteses, protocolo
experimental e métricas, está em [`delineamento_pesquisa_mestrado.md`](delineamento_pesquisa_mestrado.md);
o plano de execução em [`plano_implementacao.md`](plano_implementacao.md).

**Retomando o trabalho? Comece por [`HANDOFF.md`](HANDOFF.md)** — estado por
frente, artefatos canônicos com hash, decisões em aberto e a sequência de
retomada em ordem de dependência.

## Onde o trabalho está

| Frente | Estado |
| :--- | :--- |
| Baseline clássica (WP0) | medida: 98–100% de detecção em água limpa, 60% no vídeo de menor nitidez |
| Detector fiducial profundo (WP3a) | v1 + v3 avaliados; mediana de erro de canto 0,74–1,03 px, 0,0% de cantos acima de 5 px |
| Calibração intrínseca (WP1 / Exp. 0) | importada do projeto `vrchat` (Caliscope, S600 @1920×1080, RMSE 0,533 px); falta validar a transferência nesta bancada |
| Calibração refrativa (H₂) | não iniciada |
| Ground truth eletromecânico | não iniciado — bloqueia toda afirmação de acurácia |

## Estrutura

    calibracao/        importação e validação da calibração intrínseca
    treino_fiducial/   detector profundo de cantos ChArUco (PyTorch)
    survey/            revisão bibliográfica
    data/              aquisições .m2k (não versionado, ~3,5 GB)
    videos/            vídeos de tanque (não versionado, ~580 MB)

## Calibração

A calibração intrínseca não é medida aqui. Ela vem do projeto `vrchat`, onde a
mesma câmera física (EMEET SmartCam S600) foi calibrada com Caliscope 0.11.3 em
2026-08-05 — 30 quadros, RMSE 0,533 px, cobertura 0,92.

```bash
cd calibracao
python teste_caliscope.py          # verifica o pipeline antes de medir
python validar_transferencia.py --perfil perfis_ativos/s600.json \
                                --capturas capturas_validacao --registrar
```

O passo a passo está em [`calibracao/GUIA_SESSAO.md`](calibracao/GUIA_SESSAO.md)
e as decisões de método em [`calibracao/README.md`](calibracao/README.md).

O pipeline próprio de captura e ajuste foi aposentado em 2026-08-07: ele produziu
uma calibração **reprovada pelos próprios critérios** (9 vistas de 25, IC 95% de
`fx` com 61,5% de largura), e a mesma câmera já tinha sido calibrada corretamente
sete dias depois no outro projeto.

Pontos de método que valem para o resto do projeto:

- **Critérios de aceite pré-registrados**, fixados antes da primeira medição.
  Critério que falha se corrige recapturando, não relaxando o número.
- **Mesma câmera não é mesma calibração.** Reaproveitar `K` medido em outro
  projeto é hipótese, não dado: foco, campo de visão e resolução mudam
  `fx, fy, cx, cy` sem deixar rastro no arquivo. O perfil importado só sai de
  `nao_validada` depois de medido nesta bancada.
- **Resíduo baixo não prova escala certa.** O `solvePnP` absorve `fx` errado na
  profundidade — com `fx` 5% fora, o erro mediano fica em 0,17 px. Por isso o
  gate mede a escala explicitamente e há uma prova com trena.
- **Nada é reportado sem dispersão**: mediana, P90, máximo e IC 95%. Média
  sozinha esconde outliers catastróficos, como a auditoria do ciclo v2 do
  detector mostrou.
- **O que não é medido não é afirmado.** O foco da S600 variou entre 200 e 281
  durante o gate do vrchat; isso está registrado no perfil como alerta, não
  presumido travado.

## Verificação

    cd calibracao
    python teste_caliscope.py   # selo, manifesto e o gate de transferência

O teste aprova um `K` correto (mediana 0,094 px, escala 1,00007) e **reprova**
um `fx` 5% errado (escala 1,0496), recuperando o fator real. Um gate que só
olhasse resíduo teria aprovado o segundo caso.

## Dados não versionados

Aquisições, vídeos, recortes de treino, pesos `.pt` e ambientes virtuais estão
fora do git (ver `.gitignore`). São insumo experimental, não código — cada
versão de um binário de centenas de MB ficaria permanentemente no histórico.
Os pseudo-rótulos do treino ficam versionados por definirem o conjunto.
