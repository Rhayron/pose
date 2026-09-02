# Roteiro de experimentos — pose e sincronização (sem refração)

**Data:** 2026-09-02 · **Escopo declarado:** estimativa de pose e sincronização
vídeo↔ultrassom. A calibração refrativa **não** será feita agora; nenhum número
em milímetros é reivindicado neste roteiro. Refrativa, mão-olho e ground truth
eletromecânico seguem adiados por decisão (ver `HANDOFF.md`).

**O que isso implica nas métricas.** Sem refração, a pose PnP com o K de ar
carrega um erro sistemático desconhecido de escala e profundidade. Por isso
todas as métricas deste roteiro são *internas* — pixels de reprojeção, taxas de
detecção, repetibilidade em janelas paradas, concordância entre métodos — e
nenhuma delas depende de converter pixel em milímetro. Isso não é uma
limitação disfarçada: é o desenho. As grandezas internas são exatamente as que
transferem quando a refração entrar.

---

## Cadeia de dependências

```
E0 (aparato são) → E1 (campanha de takes) → E2 (detecção 4K)
                                          → E3 (pose PnP)      → E5 (pose↔US)
                                          → E4 (sincronização) ↗
E6 (fine-tuning 4K) é opcional e depende de E2 mostrar gap de domínio.
```

---

## E0 — Saúde do aparato de captura (~1 h de bancada, antes de qualquer take)

Motivado pelos dois problemas do smoke `20260901_165544_983`: fps medido de
20,79 (não 30) e trava de autofoco sem confirmação. A trava agora tem gate no
próprio `gravar.py` (PREPARAR só chega a PRONTO com foco comprovadamente
estável); resta o fps.

| # | Tarefa | Critério de aceitação |
| :--- | :--- | :--- |
| E0.1 | Rodar PREPARAR com o gate novo; teste adversarial: mover a mão a ~20 cm da lente durante a verificação | PRONTO com "foco estável"; o foco NÃO muda durante o teste adversarial |
| E0.2 | Medir `fps_medido` em três níveis de iluminação (ambiente; +1 refletor; +2 refletores), smoke de 30 s cada | `fps_medido ≥ 28` no nível escolhido para a campanha, OU decisão registrada de aceitar ~21 fps com o blur medido |
| E0.3 | Medir a latência do pipeline com `medir_latencia.py` nesta montagem | valor em ms registrado; passa a ser o `--latencia-ms` de todos os takes |

**Hipótese do fps** (a confirmar em E0.2): a autoexposição está ativa (readback
`-1`, não observável) e alonga o shutter em luz fraca; o período medido de
48 ms é consistente com shutter de ~1/21 s. Mais luz → shutter menor → fps
recupera **e** o motion blur cai junto. Dois problemas, uma causa, uma correção.

**Saída:** nota curta no repositório com os três números e a decisão de
iluminação. Nenhum take de campanha antes de E0 fechar.

---

## E1 — Campanha de takes sincronizados (vídeo 4K + `.m2k`)

Cada take produz um par casado: `video_<id>.avi` + `sessao_<id>.json` no
repositório de sessões e o `.m2k` copiado para o mesmo id.

**Matriz mínima (12 takes + margem):**

| Fator | Níveis |
| :--- | :--- |
| Trajetória | linear (varredura ao longo do tubo); orbital/isométrica (giro em torno da região) |
| Velocidade | lenta (~metade do normal); normal |
| Repetições | 3 por célula |
| Água | condição atual do tanque (limpa); turbidez fica para campanha futura |

**Protocolo por take (ritual fixo):**

1. PREPARAR — gate de foco tem de aprovar. Se reprovar, parar e resolver.
2. ARMAR — pré-roll começa.
3. Clique **START** no Multi2000 (fora da janela do app) — marcador grosseiro.
4. **Ritual de sincronização** (ver seção própria): 3 batidas da sonda na
   peça, pausa de 2 s, e só então a trajetória.
5. Trajetória com **paradas deliberadas** de ~2 s a cada ~5 s (stop-and-go).
6. 3 batidas finais + pausa, PARAR, aguardar SALVO.
7. Copiar o `.m2k` para a pasta da sessão; anotar nas notas do app qualquer
   anomalia (bolha, reflexo, oclusão pela mão).

**Critérios de aceitação por take:** `descartes = 0`; `fps_medido` dentro do
decidido em E0; JSON com `sincronismo.qualidade.nivel` pelo menos `grosseira`;
marcador ArUco visível a olho no preview durante ≥ 90% da trajetória.

**Critério da campanha:** ≥ 12 takes válidos cobrindo a matriz; qualquer take
reprovado é regravado, não remendado.

---

## E2 — Detecção no domínio real (4K, água, tanque)

O detector v1+v3 foi treinado e avaliado sobre os vídeos 1080p de 27/05.
Transferência para 4K/condições novas é hipótese, não fato, até este
experimento medir.

| # | Tarefa | Métrica | Critério |
| :--- | :--- | :--- | :--- |
| E2.1 | ArUco OpenCV (baseline) em todos os quadros dos takes de E1 | taxa de detecção por take | referência; sem gate |
| E2.2 | Detector v1+v3 nos mesmos quadros | taxa de detecção; taxa de rejeição do v3 | taxa ≥ baseline nos quadros em que a baseline falha ou degrada |
| E2.3 | Concordância de cantos nos quadros em que ambos detectam | discrepância por canto (px) | P90 < 2 px (consistente com a régua do v3) |
| E2.4 | Confirmação pendente do v3: n=200 no conjunto de teste de treino | mesmas métricas de `RESULTADOS_V3.md` | veredicto mantido |
| E2.5 | Decisão *a priori* sobre o nível "leve" (K=5 ou aceite 0,80) — registrar a régua ANTES, validar em amostra nova | perda de detecção ≤ 10 p.p. | decidido antes de ver os números |

**Saída:** tabela por take, e a decisão de qual detector alimenta E3 (pode ser
"clássico onde ele funciona, profundo nos degradados" — a fusão H₁ começa aqui
como seleção simples).

---

## E3 — Pose PnP e qualidade de trajetória (sem milímetros)

PnP (`IPPE_SQUARE` para o marcador único; `SQPnP` quando houver mais pontos)
com o K selado de `perfis_ativos/s600.json`. Métricas independentes de escala:

| Métrica | O que mede | Critério |
| :--- | :--- | :--- |
| Erro de reprojeção por quadro (px) | consistência interna do PnP | mediana < 1 px nos quadros aceitos |
| Taxa de convergência | robustez | > 95% dos quadros com detecção |
| **Jitter nas paradas** | repetibilidade estática da pose SEM ground truth: nas janelas paradas do stop-and-go a pose verdadeira é constante; todo desvio ali é ruído do pipeline | número de referência interno, reportado como desvio-padrão de t (unidades nominais) e de R (graus) por janela |
| Flips do IPPE | ambiguidade de pose planar (marcador único de 4 cantos coplanares) | flips detectados e resolvidos por continuidade temporal; taxa de flip reportada |
| Suavidade da trajetória | consistência temporal | espectro de alta frequência antes/depois de filtro (protótipo da fusão H₁) |

**A jogada dupla do stop-and-go:** as mesmas paradas servem à sincronização
(E4) e à medição de precisão interna sem GT (aqui). Um protocolo, dois
experimentos.

**Saída:** trajetórias 6DoF por take (formato próprio, com timestamps
monotônicos), curvas de reprojeção, e o relatório de jitter estático — este
número é a melhor aproximação de precisão disponível até existir GT.

---

## E4 — Sincronização vídeo↔ultrassom

Estimar o offset entre o relógio dos quadros (monotônico do PC, por quadro) e
o eixo temporal do `.m2k` (PRF 3633 Hz, aquisição indexada por tempo), por
**métodos redundantes**, e validar por concordância. Os métodos estão
detalhados na seção seguinte; aqui, o desenho experimental:

| # | Método | Estimativa que produz |
| :--- | :--- | :--- |
| E4.1 | Clique global (já registrado no JSON) | prior grosseiro do offset |
| E4.2 | Batidas mecânicas (início e fim do take) | offset ± ~1 quadro; com dois eventos, também a deriva de relógio |
| E4.3 | Stop-and-go (correlação de perfis de movimento) | offset ± ~1 quadro + deriva, ao longo do take inteiro |
| E4.4 | Relógio comum do PC (timestamp do `.m2k`, se o XML tiver) | prior independente, resolução de ~1 s |

**Métrica de validação:** concordância entre E4.2 e E4.3 — se os dois offsets
independentes concordam dentro de 1 período de quadro (~48 ms a 21 fps), a
sincronização está triangulada. O clique (E4.1) e o relógio (E4.4) servem para
desambiguar múltiplos picos de correlação, não como estimativa final.

**Critério de aceitação:** offset por take com incerteza ≤ 1 período de quadro
pela via de custo zero; deriva de relógio medida (ou limitada) por take de
~60 s; o método vencedor documentado como padrão da campanha.

**Fora do critério, dentro do roteiro:** especificar o upgrade para nível
`fina` (LED, já suportado por `--roi` + `detectar_evento_luminoso`, que
interpola a transição dentro do quadro) — ver seção de sincronização.

---

## E5 — Casamento pose↔US: o entregável intermediário

Com offset (E4) e trajetória (E3):

1. Interpolar a pose no instante de cada quadro/disparo do US, propagando a
   incerteza temporal do offset (uma pose interpolada com ±48 ms de incerteza
   temporal numa trajetória a velocidade v carrega ±v·48 ms de incerteza
   espacial — reportar as duas).
2. Produzir a primeira visualização de ponta a ponta: trajetória da sonda no
   tempo + posições dos disparos do `.m2k` no mesmo eixo temporal.
3. Congelar o formato de dado "pose por disparo" que a Fase 2 (registro 3D)
   vai consumir.

**Critério:** pipeline roda de ponta a ponta num comando por take; o artefato
declara explicitamente (no próprio arquivo) que a escala é nominal e a
incerteza temporal herdada do nível de sincronismo.

**Este é o marco do roteiro.** Tudo depois dele (registro volumétrico,
refração, GT, mm) é Fase 2 e tem os pré-requisitos que o `HANDOFF.md` adiou de
propósito.

---

## E6 (opcional) — Fine-tuning no domínio 4K

Só se E2 mostrar gap de domínio (queda de taxa ou de precisão do detector
profundo nos takes 4K):

- Pseudo-labels nos quadros de consenso (clássico e profundo concordando
  < 1 px) dos takes novos → fine-tuning → reavaliar com a régua de E2.
- Partição por take/sessão, nunca por quadro (anti-vazamento, como sempre).

---

# Formas de sincronizar pose ↔ ultrassom

O problema: o vídeo tem carimbos monotônicos por quadro no relógio do PC; o
`.m2k` tem um eixo temporal próprio (PRF constante) sem evento comum
registrado. Sincronizar = estimar offset (e deriva) entre os dois eixos.

Ranqueadas por custo de implantação. Níveis referem-se ao vocabulário do JSON
de sessão (`grosseira` / `um_quadro` / `fina`).

## S1 — Clique global (implementado, nível `grosseira`)

O mesmo clique que aciona o START do Multi2000 é carimbado pelo listener
global. Entre o clique e o primeiro disparo do pulser há a latência do
software proprietário: desconhecida, provavelmente variável.

- **Vale para:** casar arquivo↔arquivo, desambiguar correlações.
- **Não vale para:** associar pose a A-scan.
- **Custo:** zero (já existe).

## S2 — Batida mecânica: o "claquete" acústico (recomendado, nível `um_quadro`)

Três batidas leves da sonda contra a peça no início e no fim do take. O evento
é visível **nos dois canais ao mesmo tempo**: no vídeo, como parada abrupta do
movimento do marcador (pico de desaceleração da pose); no ultrassom, como
transiente mecânico de banda larga atravessando os A-scans (o choque excita o
transdutor de forma inconfundível contra o eco estacionário).

- **Estimador:** correlação cruzada entre |aceleração| da pose (derivada dos
  carimbos por quadro) e energia transiente do RF (janela deslizante sobre os
  A-scans). Três batidas dão um padrão de correlação com pico bem definido.
- **Dois eventos (início e fim)** dão dois offsets → deriva de relógio do take
  inteiro, de graça.
- **Precisão esperada:** ~1 período de quadro (48 ms a 21 fps; 33 ms a 30).
  Do lado do US a resolução é de sobra (PRF 3633 Hz); o gargalo é o fps.
- **Custo:** zero em hardware; um passo no ritual de gravação + o estimador em
  pós-processamento.

## S3 — Stop-and-go: correlação de perfis de movimento (nível `um_quadro`, redundante com S2)

Paradas deliberadas de ~2 s durante a trajetória. No vídeo: velocidade da pose
≈ 0. No ultrassom: A-scans consecutivos ficam altamente correlacionados quando
a sonda para (a cena acústica congela) e decorrelacionam em movimento.

- **Estimador:** binarizar os dois canais em movimento/parado (limiar sobre
  |v| da pose; limiar sobre 1−corr(A-scanₖ, A-scanₖ₊₁)) e correlacionar os
  perfis binários. Usa o take **inteiro** como assinatura, não um evento só —
  robusto a falhas locais de detecção.
- **Bônus:** mede deriva continuamente, e as mesmas janelas paradas alimentam
  o jitter estático de E3.
- **Custo:** zero em hardware; já embutido no protocolo de E1.

## S4 — Relógio comum do PC (prior barato, resolução ~1 s)

Câmera e Multi2000 rodam no mesmo PC. O JSON da sessão já grava âncora
wall-clock↔monotônico; se o XML do `.m2k` registrar o instante de início da
aquisição (verificar nos descritores — custo de um parsing), há um prior
independente com resolução de segundos.

- **Vale para:** desambiguar picos de correlação de S2/S3, sanidade.
- **Custo:** só leitura do XML.

## S5 — LED no campo de visão (upgrade planejado, nível `fina`)

Um LED dentro do quadro, acionado pelo **sinal físico** que marca o início da
aquisição. O `gravar.py` já suporta: `--roi X Y W H` amostra o brilho por
quadro e `detectar_evento_luminoso` interpola a transição *dentro* do quadro
(fração da exposição), levando a incerteza para a casa do milissegundo.

- **Requisito real:** acesso a uma saída de sincronismo/trigger do Multi2000
  (trigger-out/gate). **Não** vale acionar o LED com a mão junto do clique —
  isso só adiciona o tempo de reação humana ao problema.
- **Precisão esperada:** ms (nível `fina` do JSON, com interpolação).
- **Custo:** eletrônica trivial (LED + resistor + transistor no sinal de
  trigger) + confirmar no manual do Multi2000 qual conector expõe o evento.

## S6 — Trigger-out → microcontrolador (endgame antes do GT)

O mesmo sinal de trigger alimenta um microcontrolador que (a) acende o LED de
S5 e (b) loga cada pulso com timestamp via serial no relógio do mesmo PC.
Fecha o sincronismo **por disparo**, não por take.

- **Vale quando:** a Fase 2 exigir pose por A-scan individual (registro fino).
- **Custo:** moderado (Arduino + cabo + firmware de 30 linhas); é o degrau
  natural antes do ground truth eletromecânico.

## Recomendação operacional

**Agora (campanha E1):** S1 + S2 + S3 + S4 simultâneos — redundância de custo
zero, validação por concordância (E4). O ritual de gravação embute S2 e S3 no
protocolo; S1 já sai de graça; S4 é um parsing.

**Próximo upgrade:** S5 assim que o conector de trigger for identificado —
sobe o nível declarado no JSON de `grosseira`/`um_quadro` para `fina` sem
mudar nada no resto do pipeline (o campo `sincronismo.qualidade` já existe
para isso).

**Fase 2:** S6 quando o registro exigir pose por disparo.

---

# O que este roteiro NÃO reivindica

- Nenhum número em milímetros ou graus absolutos contra referência externa —
  não há GT nem refração calibrada.
- Nenhuma associação quadro↔A-scan individual antes de S5 — o nível declarado
  no JSON de cada sessão é o teto do que o dado autoriza.
- Nenhuma generalização para turbidez/oclusão — a campanha atual é em água
  limpa; degradação é campanha futura (Exps. 1–2 do delineamento).
