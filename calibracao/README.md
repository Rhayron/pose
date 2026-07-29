# Calibração intrínseca da câmera (WP1 · Exp. 0)

Destrava a **pose métrica** do projeto: sem estes números, o PnP sobre os cantos
entregues pelo detector v1+v3 sai em unidade arbitrária, e nenhuma hipótese
(H₁–H₄) é testável em milímetros.

**Escopo:** calibração **em ar**, câmera → objeto, sem interface água/vidro.
É a condição de controle (modelo *pinhole*) contra a qual H₂ vai comparar a
calibração refrativa. Não substitui a calibração subaquática.

---

## App (tkinter)

```bash
cd calibracao
python app.py
```

Uma janela com as quatro etapas em abas, na ordem: **Tabuleiro → Captura →
Calibrar → Validar**. A aba de captura tem preview ao vivo, painel de cobertura
(grade 3×3 + contadores por escala e inclinação) e atalhos `Espaço` / `U`.

A GUI **não reimplementa nada**: a captura usa o mesmo `SessaoCaptura` da CLI, e
calibrar/validar são chamados como subprocessos dos mesmos scripts. Resultado
produzido pela janela e pelo terminal é o mesmo objeto experimental — a régua
pré-registrada vale para os dois, e `sessao.json` registra em qual interface a
captura foi feita.

Sem dependências novas (tkinter é padrão do Python; Pillow é usado se existir,
senão o preview cai para PPM base64, nativo do Tk).

## Ordem de execução (linha de comando)

```bash
cd calibracao

# 0. VERIFICAR O INSTRUMENTO antes de medir o mundo (~1 min)
python teste_sintetico.py

# 1. Gerar o tabuleiro imprimível
python gerar_tabuleiro.py
#    -> imprimir saida/tabuleiro.svg em 100% / tamanho real
#    -> conferir a régua de 100 mm, medir 1 quadrado, escrever o valor
#       em square_mm_medido dentro de saida/tabuleiro.json

# 2. Capturar as vistas (webcam, ~10 min)
python capturar.py --resolucao 1280 720

# 3. Calibrar
python calibrar.py --imagens capturas/<sessao> --nome-camera webcam_pc

# 4. Validar em vistas NOVAS (capturar mais ~10 antes)
python validar.py --calibracao saida/calibracao_webcam_pc.json \
                  --imagens capturas/<sessao_validacao> \
                  --distancia-real-mm 600 --imagem-distancia img_0003.png
```

Dependências: `opencv-contrib-python` e `numpy` (a `.venv` de `treino_fiducial`
já serve). O `teste_sintetico.py` foi executado em OpenCV 4.13 / NumPy 2.2.

---

## Por que cada script existe

| Script | Papel |
| :--- | :--- |
| `app.py` | Interface tkinter com as quatro etapas. Casca fina sobre os módulos abaixo. |
| `nucleo.py` | Fonte única dos parâmetros do tabuleiro, da detecção e da contabilidade de cobertura. Captura e calibração usando tabuleiros diferentes é o erro silencioso clássico. |
| `captura_core.py` | Câmera, sessão de captura e overlay — compartilhado entre GUI e CLI. |
| `gerar_tabuleiro.py` | Tabuleiro ChArUco em SVG com página em **mm exatos** + régua de verificação impressa + `tabuleiro.json` (o contrato). |
| `capturar.py` | Versão CLI da captura: trava os automatismos da webcam e **relê** o que ficou; rejeita quadros borrados; guia a diversidade de poses; grava PNG sem perdas. |
| `calibrar.py` | Ajuste, **seleção do modelo de distorção por erro em dados retidos**, IC 95% por bootstrap, distribuição completa do erro, veredicto contra régua pré-registrada. |
| `validar.py` | Três provas independentes: reprojeção em sessão nova, retidão após corrigir a distorção, e distância PnP vs. trena. |
| `teste_sintetico.py` | Renderiza o tabuleiro com uma câmera conhecida e verifica se o pipeline a recupera. Testa o instrumento antes da medida. |
| `teste_captura.py` | Testa o núcleo de captura sem GUI: aceite/recusa de quadro, bins, desfazer, retomada de sessão. |
| `teste_e2e.py` | Ensaio geral: contrato → sessão A → calibrar → sessão B independente → validar, com câmera e distâncias conhecidas. |

---

## Decisões metodológicas (e o que elas evitam)

**Dicionário `DICT_4X4_50`.** O aparato do tanque já usa 7×7 (ID 0) e 5×5 (ID 3).
Dicionário distinto evita colisão de IDs quando tabuleiro e braçadeira aparecerem
no mesmo quadro — o que vai acontecer na calibração refrativa.

**A escala métrica vem de UM número medido.** `square_mm_medido`. Impressora é
instrumento não calibrado: um desvio de 4% na impressão vira 4% de erro em toda
distância estimada, e nenhum diagnóstico de reprojeção detecta isso — a
reprojeção fica perfeita, só a escala está errada. Por isso `calibrar.py` se
recusa a rodar enquanto o campo estiver `null`.

**Autofoco travado.** Autofoco muda a distância focal entre quadros; o ajuste
então estima um `f` que não existiu em nenhum instante. `capturar.py` tenta
travar e **relê os valores efetivos** — driver que ignora o pedido aparece
marcado com `!!` no console e fica registrado em `sessao.json`.

**PNG, nunca JPEG.** Compressão com perdas desloca cantos em fração de pixel —
exatamente a grandeza medida.

**Modelo de distorção escolhido por hold-out, não por RMS.** O RMS de reprojeção
sempre cai ao adicionar coeficientes; escolher por ele seleciona sobreajuste com
certeza. Quatro candidatos (`k1k2`, `+tangencial`, `+k3`, `racional`) competem
por erro mediano em vistas retidas, em 20 partições 70/30, e vence o **mais
simples dentro de 0,02 px do melhor**.

**Nada é reportado sem dispersão.** A auditoria v2 do detector mostrou que média
esconde outliers catastróficos. Aqui sai mediana, P90, P99, máximo, fração acima
de 1 px, por vista e agregado, mais IC 95% dos intrínsecos por bootstrap **sobre
as vistas** (a variabilidade que importa é entre-vistas, não entre-cantos).

**Cobertura é critério, não conselho.** Sem tabuleiro nas bordas, `k1`/`k2` são
extrapolação; sem inclinação, `f` e a distância ficam correlacionados e o ajuste
é quase degenerado. Ambos produzem RMS baixo com parâmetros errados — o modo de
falha mais perigoso, porque parece sucesso.

---

## Régua pré-registrada

Fixada em 29/07/2026, **antes da primeira captura** (`CRITERIOS` em `calibrar.py`,
`METAS_COBERTURA` em `nucleo.py`). Alterar qualquer valor depois de ver um
resultado é mover a régua. Critério que falha se corrige **recapturando**.

| Critério | Limite |
| :--- | :--- |
| Vistas aceitas | ≥ 25 |
| Cobertura | 9/9 células, ≥ 4 vistas por bin de escala, ≥ 8 inclinadas (>15°), ≥ 5 muito inclinadas (>35°) |
| RMS global | ≤ 0,50 px |
| P90 do erro por canto | ≤ 1,00 px |
| Erro mediano em hold-out | ≤ 0,60 px |
| Largura do IC 95% de `fx` | ≤ 2% de `fx` |

Diagnósticos informativos (não reprovam): assimetria `fx`/`fy` ≤ 2%, desvio do
centro óptico ≤ 10% da dimensão.

---

## Protocolo de captura (~10 min)

1. Iluminação difusa e constante. Sem flicker de lâmpada; se houver, feche o
   obturador para múltiplo de 1/100 s (rede 50 Hz) ou 1/120 s (60 Hz).
2. **Resolução idêntica à dos experimentos.** Intrínsecos não escalam entre modos
   da webcam — trocar de 1280×720 para 1920×1080 invalida `fx, fy, cx, cy`.
3. Tabuleiro colado em superfície rígida e plana. Papel ondulado vira erro
   sistemático que a calibração não distingue de distorção de lente.
4. Mover o **tabuleiro**, não a câmera (a webcam do PC costuma estar fixa).
5. Cobrir: cada uma das 9 células da grade; três escalas (longe, médio, perto,
   com o tabuleiro chegando a ocupar boa parte do quadro); inclinações fortes em
   direções diferentes (±30–45° em torno de ambos os eixos), incluindo vistas nos
   **cantos** do quadro — é lá que a distorção é grande e mal amostrada.
6. Parar quando o HUD mostrar todas as metas atendidas.

Depois, capture uma **sessão separada de ~10 vistas** só para `validar.py`. Sem
isso não há prova de generalização — só o erro de ajuste, que é otimista por
construção.

---

## Verificação já executada

`teste_sintetico.py` renderiza 36 vistas de uma câmera de referência
(1280×720, `fx`=905, `fy`=902, `cx`=646, `cy`=351, `k1`=−0,185, `k2`=0,042,
tangencial pequena) e roda `calibrar.py` sobre elas. Resultado em 29/07/2026,
OpenCV 4.13, semente 123:

| Parâmetro | Recuperado | Referência | Desvio |
| :--- | ---: | ---: | ---: |
| fx | 904,04 | 905,00 | −0,11% |
| fy | 900,94 | 902,00 | −0,12% |
| cx | 649,06 | 646,00 | +3,06 px |
| cy | 352,29 | 351,00 | +1,29 px |
| k1 | −0,1835 | −0,1850 | −0,8% |
| RMS | 0,228 px | — | — |

O `fx` de referência caiu **dentro** do IC 95% do bootstrap ([901,8; 906,1]) —
ou seja, a incerteza reportada é honesta, não decorativa. `validar.py` sobre 12
vistas independentes: reprojeção mediana 0,12 px, retidão mediana 0,05 px.

Observação registrada: a seleção parcimoniosa escolheu `k1k2` embora a referência
tivesse componente tangencial (p₁=0,0012, p₂=−0,0008). Correto — a contribuição
dela está abaixo do ruído das vistas, e incluí-la não melhora o erro em dados
retidos. Na webcam real o resultado pode ser outro; quem decide é o hold-out.

O veredicto de **cobertura** reprova no teste sintético: o amostrador de poses
não foi escrito para otimizar cobertura. Isso é esperado e não afeta o que o
teste afere.

`teste_captura.py` exercita o núcleo de captura com quadros sintéticos: 17
verificações, todas passando — detecção, recusa por nitidez e por ausência de
tabuleiro, gravação em PNG, numeração sem colisão, teto de bin fechando a
captura automática, desfazer, e retomada de sessão a partir do disco com estado
idêntico ao original.

`teste_e2e.py` encadeia as quatro etapas com câmera e distâncias conhecidas.
Resultado em 29/07/2026:

| Verificação | Resultado |
| :--- | :--- |
| Recusa calibrar sem quadrado medido | guarda funcionou |
| fx recuperado | 906,32 vs 905,00 |
| Centro óptico | (648,5; 352,0) vs (646; 351) |
| Reprojeção em vistas independentes | mediana 0,158 px · P90 0,313 |
| Retidão após corrigir distorção | mediana 0,062 px |
| **Distância PnP vs. distância verdadeira** | **522,5 vs 521,7 mm (+0,15%)** |

A última etapa do ensaio recalibra com o quadrado declarado 4% menor que o real.
Os intrínsecos e o RMS ficam **idênticos** — o erro de impressão é invisível em
todo diagnóstico de reprojeção e reaparece inteiro, como 4%, em cada distância
estimada. É a demonstração de por que a medida com paquímetro é obrigatória.

**O que NÃO foi testado automaticamente:** a janela em si. O ambiente onde estes
scripts foram desenvolvidos não tem tkinter nem display, então a GUI foi
verificada por análise estática (pyflakes limpo em todos os arquivos) e pelo
teste do núcleo que ela aciona. O primeiro `python app.py` na sua máquina é o
teste de fumaça que falta.

---

## O que esta calibração NÃO resolve

- **Refração.** Filmar através de vidro e água quebra o modelo pinhole. Estes
  intrínsecos em ar são a condição de controle do Experimento 3, não a solução.
- **Os 13 vídeos de 27/05.** Foram gravados com outra câmera; continuam sem
  escala métrica. Só uma calibração daquela câmera, na mesma configuração,
  daria pose em mm retroativamente.
- **Ground truth.** Calibração dá escala, não referência. A acurácia de pose
  continua sem padrão-ouro até o sistema eletromecânico do WP1.
- **A geometria do aparato.** Com um só marcador visível por quadro, a pose
  segue mal condicionada em profundidade e orientação, calibrada ou não.
