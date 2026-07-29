# pose

Estimação visual de pose 6DoF de transdutor ultrassônico e registro espacial 3D
de imagens de ultrassom para inspeção subaquática por END.

Pesquisa de mestrado. O delineamento completo, com hipóteses, protocolo
experimental e métricas, está em [`delineamento_pesquisa_mestrado.md`](delineamento_pesquisa_mestrado.md);
o plano de execução em [`plano_implementacao.md`](plano_implementacao.md).

## Onde o trabalho está

| Frente | Estado |
| :--- | :--- |
| Baseline clássica (WP0) | medida: 98–100% de detecção em água limpa, 60% no vídeo de menor nitidez |
| Detector fiducial profundo (WP3a) | v1 + v3 avaliados; mediana de erro de canto 0,74–1,03 px, 0,0% de cantos acima de 5 px |
| Calibração intrínseca (WP1 / Exp. 0) | pipeline pronto e verificado; sessão em andamento |
| Calibração refrativa (H₂) | não iniciada |
| Ground truth eletromecânico | não iniciado — bloqueia toda afirmação de acurácia |

## Estrutura

    calibracao/        pipeline de calibração intrínseca (app + CLI + testes)
    treino_fiducial/   detector profundo de cantos ChArUco (PyTorch)
    survey/            revisão bibliográfica
    data/              aquisições .m2k (não versionado, ~3,5 GB)
    videos/            vídeos de tanque (não versionado, ~580 MB)

## Calibração

```bash
cd calibracao
python teste_sintetico.py      # verifica o pipeline antes de medir
python app.py                  # ou iniciar_app.bat no Windows
```

O passo a passo da sessão está em [`calibracao/GUIA_SESSAO.md`](calibracao/GUIA_SESSAO.md)
e as decisões de método em [`calibracao/README.md`](calibracao/README.md).

Pontos de método que valem para o resto do projeto:

- **Critérios de aceite pré-registrados**, fixados antes da primeira medição.
  Critério que falha se corrige recapturando, não relaxando o número.
- **Modelo de distorção escolhido por erro em dados retidos**, não por RMS de
  treino — RMS sempre cai ao adicionar coeficientes, então escolher por ele
  seleciona sobreajuste com certeza.
- **Nada é reportado sem dispersão**: mediana, P90, máximo e IC 95% por
  bootstrap. Média sozinha esconde outliers catastróficos, como a auditoria do
  ciclo v2 do detector mostrou.
- **O que não é medido não é afirmado.** Se o driver ignora a trava de foco, o
  app amostra a propriedade durante a sessão e registra se ela variou.

## Verificação

    python teste_sintetico.py   # recupera uma câmera de referência conhecida
    python teste_e2e.py         # cadeia completa, com distâncias conhecidas
    python teste_captura.py     # núcleo de captura
    python teste_loop.py        # resiliência da thread de captura

Últimos resultados: `fx` recuperado a −0,11% do valor de referência, com o
valor verdadeiro dentro do IC 95% do bootstrap; distância por PnP a +0,15% da
distância verdadeira.

## Dados não versionados

Aquisições, vídeos, recortes de treino, pesos `.pt` e ambientes virtuais estão
fora do git (ver `.gitignore`). São insumo experimental, não código — cada
versão de um binário de centenas de MB ficaria permanentemente no histórico.
Os pseudo-rótulos do treino ficam versionados por definirem o conjunto.
