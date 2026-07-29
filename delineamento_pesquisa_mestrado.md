# Delineamento de Pesquisa de Mestrado

## Estimação Visual de Pose 6DoF de Transdutor Ultrassônico e Registro Espacial Tridimensional de Imagens de Ultrassom para Inspeção Subaquática por Ensaios Não Destrutivos

**Programa:** CPGEI / PPGCA — Universidade Tecnológica Federal do Paraná (UTFPR)
**Laboratório:** LASSIP — Laboratório de Sistemas e Instrumentação em Processamento de Sinais
**Orientador:** Prof. Dr. Thiago Alberto Rigo Passarin
**Mestrando:** Rhayron de Sousa Nogueira
**Colaboradores técnicos:** Thiago E. Kalid (montagem experimental), Daniel Santin, Hector L. M.

> **Nota de integridade bibliográfica.** Todas as referências citadas ao longo deste documento derivam do survey previamente conduzido e devem ser **verificadas individualmente contra a base original (DOI resolvível, autores e ano corretos) antes de comporem a versão final da dissertação**. Esta exigência atende diretamente à observação do orientador quanto ao risco jurídico e de credibilidade associado a referências não confirmadas. Nenhuma referência deste delineamento deve ser considerada estabelecida sem auditoria manual prévia.

---

## Resumo

A inspeção subaquática de dutos e estruturas metálicas por ultrassom depende, tradicionalmente, de scanners motorizados, braços robóticos ou encoders eletromecânicos acoplados ao transdutor para registrar espacialmente cada aquisição. Esses aparatos impõem restrições de acesso, sofrem escorregamento mecânico, exigem manutenção e limitam a inspeção a trajetórias pré-programadas. Este trabalho propõe substituir a odometria eletromecânica por um sistema de **estimação visual de pose 6DoF** (seis graus de liberdade — três de translação e três de orientação) do transdutor, baseado em visão computacional e aprendizado profundo, robusto às degradações ópticas do meio aquático (turbidez, *backscatter*, atenuação cromática e distorção refrativa). O sistema combina duas estratégias complementares: estimação de *keypoints* por campos vetoriais densos (inspirada na arquitetura PVNet) e detecção de marcadores fiduciais robusta a iluminação adversa (inspirada no Deep ChArUco). A pose estimada é então utilizada para posicionar espacialmente, em um referencial tridimensional, imagens de ultrassom previamente reconstruídas por métodos consolidados de END (varredura setorial com foco, TFM ou CPWC). A validação experimental será conduzida em tanque de laboratório sobre amostra de tubulação de aço, utilizando o próprio sistema eletromecânico existente como referência de *ground truth* — o que permite quantificar rigorosamente a acurácia do sistema visual que se pretende, futuramente, empregar em substituição a ele. Espera-se demonstrar que a integração entre rastreamento visual profundo e registro espacial de dados de END constitui um caminho viável para inspeções a mão livre ou por ROV, preenchendo uma lacuna ainda não explorada na literatura.

**Palavras-chave:** estimação de pose 6DoF; visão computacional subaquática; ensaios não destrutivos; ultrassom; aprendizado profundo; marcadores fiduciais; registro espacial 3D; PVNet; Deep ChArUco.

---

## 1. Introdução e Contextualização

### 1.1. O problema da localização em inspeção ultrassônica subaquática

A integridade estrutural de dutos, risers, tanques e estruturas offshore é monitorada, em grande medida, por ensaios não destrutivos (END) por ultrassom. A técnica permite detectar e dimensionar descontinuidades internas — trincas, corrosão, faltas de fusão em soldas — sem comprometer a peça inspecionada. Contudo, o valor diagnóstico de uma medição ultrassônica não reside apenas na amplitude ou no tempo de voo do eco: reside igualmente na **rastreabilidade espacial** da falha, isto é, na capacidade de afirmar com precisão *onde*, na geometria tridimensional da peça, cada defeito se encontra. Sem esse registro espacial, uma inspeção perde reprodutibilidade, comparabilidade temporal (necessária para avaliar a progressão de uma falha entre campanhas) e utilidade para tomada de decisão em manutenção.

Historicamente, o registro espacial é obtido acoplando ao transdutor um dispositivo de medição de deslocamento: encoders rotativos, scanners de correia magnética, trilhos motorizados ou braços robóticos com cinemática conhecida. Esses sistemas convertem o movimento do transdutor em coordenadas, associando cada A-scan, B-scan ou C-scan a uma posição conhecida. A abordagem é madura e precisa, porém carrega limitações estruturais que se agravam no ambiente subaquático:

- **Restrição de acesso e geometria.** Crawlers e trilhos exigem superfícies preparadas e trajetórias regulares; geometrias complexas (junções, bocais, regiões soldadas de dupla curvatura) frequentemente são inacessíveis a esses aparatos.
- **Escorregamento e deriva mecânica.** Correias e rodas de encoder escorregam sobre superfícies molhadas, incrustadas ou irregulares, introduzindo erro acumulativo (*drift*) na estimativa de posição.
- **Massa, complexidade e manutenção.** Aparatos eletromecânicos submersíveis são pesados, caros, sujeitos a corrosão e à infiltração, e demandam manutenção frequente.
- **Rigidez operacional.** A inspeção fica limitada às trajetórias que o mecanismo consegue executar, inviabilizando a inspeção a mão livre (*freehand*) ou o aproveitamento oportunístico de um ROV que já se encontra no local.

### 1.2. Visão computacional como alternativa sem contato

A estimação de pose por visão computacional oferece uma alternativa sem contato: uma ou mais câmeras observam o transdutor (ou marcadores a ele fixados) e, a cada quadro, inferem sua posição e orientação relativas à peça. Se essa inferência for suficientemente precisa e robusta, o encoder eletromecânico pode ser dispensado, e a inspeção torna-se livre de trajetória: qualquer movimento do transdutor — humano, robótico ou por ROV — é rastreado opticamente e convertido em registro espacial.

O desafio central é que o ambiente subaquático degrada severamente a informação visual. A luz sofre atenuação não uniforme por comprimento de onda (perda dominante do vermelho, resultando em dominância esverdeada), espalhamento por partículas em suspensão (*backscatter*, que reduz contraste e cria véu luminoso), e múltiplas refrações nas interfaces câmera–vidro–água, que invalidam o modelo de projeção *pinhole* assumido pela visão computacional convencional. A turbidez variável e a oclusão parcial do alvo (comum em espaços confinados como o interior ou o entorno de tubulações) tornam frágeis os métodos clássicos baseados em correspondência de *features* ou em detecção heurística de bordas.

### 1.3. Posicionamento e contribuição do trabalho

Este trabalho propõe e valida experimentalmente um pipeline que enfrenta essas dificuldades combinando aprendizado profundo tolerante a oclusão, detecção fiducial robusta a iluminação adversa e correção explícita da distorção refrativa. A contribuição não está em criar, isoladamente, um novo estimador de pose ou um novo algoritmo de reconstrução ultrassônica — ambos os campos possuem estado da arte consolidado —, mas sim em **integrar rastreamento visual profundo subaquático ao registro espacial tridimensional de dados de END**, uma conjunção ainda ausente na literatura (conforme a análise de lacuna detalhada na Seção 5). O escopo é deliberadamente delimitado: a reconstrução das imagens de ultrassom permanece a cargo dos métodos já dominados pelo laboratório, e as imagens chegam prontas ao pipeline; a tarefa desta dissertação encerra-se no posicionamento espacial correto dessas imagens, produzindo uma representação tridimensional registrada.

---

## 2. Fundamentação Teórica

Esta seção sintetiza os pilares teóricos sobre os quais o pipeline é construído. O tratamento aprofundado de cada tópico, com a literatura correspondente, encontra-se no survey que acompanha este delineamento; aqui, o objetivo é estabelecer o encadeamento lógico entre os conceitos e o método proposto.

### 2.1. Estimação de pose 6DoF: da correspondência clássica ao voto denso

O problema de estimação de pose 6DoF consiste em recuperar a transformação rígida — rotação **R** ∈ SO(3) e translação **t** ∈ ℝ³ — que relaciona o referencial de um objeto conhecido ao referencial da câmera. A formulação clássica resolve esse problema estabelecendo correspondências entre pontos 3D do modelo (tipicamente derivados de um modelo CAD) e suas projeções 2D na imagem, e então recuperando a pose pelo algoritmo *Perspective-n-Point* (PnP), habitualmente envolto em um laço robusto de RANSAC para rejeição de correspondências espúrias.

A fragilidade dessa formulação clássica surge quando o objeto está parcialmente ocluído, truncado pela borda da imagem, ou inserido em fundo pouco texturizado — todas condições recorrentes na inspeção de dutos. Métodos de regressão direta da pose por redes neurais, embora atrativos, generalizam mal sem fortes *priors* e tendem a produzir estimativas imprecisas sob mudança de domínio. A alternativa que fundamenta este trabalho é a predição densa de *keypoints*: em vez de regredir a pose diretamente ou depender de *features* esparsas, a rede prediz, para cada pixel pertencente ao objeto, uma grandeza que vota na localização 2D dos pontos-chave.

A arquitetura **PVNet (Pixel-wise Voting Network)** é o marco estrutural dessa linha. Ela prediz, a partir de cada pixel do objeto, um vetor unitário direcional apontando para cada ponto-chave; a localização de cada ponto-chave é então obtida por votação (interseção robusta dos vetores via RANSAC), e a pose é recuperada por PnP sobre os pontos-chave votados. A virtude dessa estratégia é a tolerância à oclusão e ao truncamento: mesmo que apenas uma fração do objeto esteja visível, os pixels visíveis continuam votando corretamente na posição dos pontos-chave, inclusive daqueles que caem fora da região visível. Essa propriedade é decisiva no contexto de inspeção, em que o transdutor pode estar parcialmente obstruído pela própria estrutura, por bolhas ou por partículas.

### 2.2. Marcadores fiduciais robustos: quando a textura natural falha

Há regimes de degradação — turbidez extrema, *backscatter* intenso, ausência de textura natural no alvo — em que a estimação puramente *markerless* torna-se instável. Nesses casos, marcadores fiduciais fixados ao conjunto transdutor/braçadeira fornecem pontos de correspondência de geometria conhecida e alto contraste. Os dicionários ArUco e os tabuleiros ChArUco (combinação de padrão de xadrez com marcadores ArUco embutidos) são padrão consolidado, mas seus detectores heurísticos clássicos — baseados em limiarização adaptativa e detecção de contornos — falham quando a imagem sofre *motion blur*, sombras severas ou perda de contraste por espalhamento.

A resposta do estado da arte é substituir o detector heurístico por detecção baseada em aprendizado profundo. A arquitetura **Deep ChArUco** emprega uma rede de detecção de pontos do tabuleiro (ChArUcoNet) seguida de uma rede de refinamento subpixel (RefineNet), operando de forma confiável em condições de iluminação severamente precárias, onde o detector clássico não binariza corretamente. Extensões subsequentes (linha DeepArUco/DeepArUco++) aprimoram a detecção de cantos sob desfoque e iluminação adversa sem sacrificar tempo de inferência. Uma tendência complementar, particularmente relevante para o meio subaquático, é o uso de **marcadores fiduciais ativos** (autoiluminados): emitir luz diretamente do marcador, em comprimentos de onda de menor atenuação (faixa azul-verde), reduz a dependência da iluminação da câmera — a qual, ao iluminar a coluna d'água entre câmera e alvo, é justamente a principal fonte de *backscatter*.

### 2.3. O problema refrativo e a calibração da visão subaquática

A visão computacional convencional assume o modelo *pinhole*: raios que convergem para um único centro óptico. Sob a água, essa hipótese é violada, pois cada raio sofre refração ao atravessar as interfaces ar–vidro (a janela ou domo do *housing* da câmera) e vidro–água. Em uma janela plana (*flat port*), a refração introduz distorção dependente do ângulo e da profundidade que **não** pode ser plenamente absorvida pelos coeficientes de distorção radial do modelo clássico; o erro residual degrada diretamente a precisão do PnP e, consequentemente, da pose. A correção rigorosa exige modelagem refrativa explícita (traçado de raios pelas interfaces) e ferramentas de calibração específicas que estimem os parâmetros geométricos das interfaces (espessura e orientação da janela, índices de refração, distância câmera–janela). A adoção de calibração refrativa é, portanto, condição necessária para que qualquer ganho de robustez das redes de estimação de pose se traduza em acurácia métrica real.

### 2.4. Realce de imagem subaquática como pré-processamento

A degradação cromática e o véu por espalhamento podem ser parcialmente mitigados por técnicas de realce (*image enhancement*): correção de dominante de cor, remoção de véu (*dehazing*) e restauração por redes neurais. O realce atua como etapa opcional de pré-processamento, elevando o contraste e a nitidez das *features* antes de alimentá-las ao estimador de pose. A eficácia desse pré-processamento sobre a acurácia final da pose é, em si, uma questão experimental a ser avaliada (ver estudos de ablação, Seção 7).

### 2.5. Reconstrução de imagens de ultrassom — contexto, não escopo

As imagens de ultrassom que o pipeline posicionará espacialmente são produzidas por métodos consolidados de END, tratados aqui como **contexto** e não como objeto de desenvolvimento. Conforme delimitação do orientador, mantém-se em aberto o método específico de reconstrução, que poderá ser: varredura setorial (S-scan) com foco, na qual as leis focais são calculadas considerando todas as refrações previstas (notadamente no caso de lente acústica); ou, na ausência de lente acústica, o *Total Focusing Method* (TFM) — que sintetiza foco em cada ponto da imagem a partir da captura completa da matriz de elementos — ou o *Coherent Plane Wave Compounding* (CPWC) — que compõe coerentemente transmissões de ondas planas em múltiplos ângulos para alta taxa de quadros. O ponto de contato desses métodos com esta pesquisa é uma premissa comum a todos eles: pressupõem amostragem em posição espacial conhecida. Qualquer movimento relativo não registrado entre transdutor e peça desfoca ou desloca espacialmente a imagem reconstruída. É precisamente esse acoplamento — a dependência da qualidade da imagem em relação ao conhecimento da pose — que motiva o rastreamento visual proposto.

### 2.6. Registro espacial tridimensional de dados de END

A etapa final do pipeline consiste em compor, em um referencial tridimensional único (o modelo CAD ou o *digital twin* da peça), o conjunto de imagens de ultrassom bidimensionais adquiridas ao longo de uma trajetória. Cada imagem, associada à pose 6DoF do transdutor no instante de sua aquisição, é transformada rigidamente para o referencial da peça, produzindo uma representação volumétrica espacialmente registrada. Trabalhos recentes em END automatizado passaram a fundir rastreamento (óptico ou por correlação da própria malha ultrassônica) à varredura, migrando do posicionamento estritamente unidimensional ("metro corrido" / tempo) para o posicionamento cartesiano em modelo 3D. A conjunção específica desse registro com rastreamento visual profundo **subaquático**, entretanto, permanece inexplorada.

---

## 3. Lacuna Científica e Justificativa

A revisão do estado da arte revela dois corpos de literatura maduros, porém disjuntos:

1. **Visão computacional subaquática e estimação de pose 6DoF submersa.** Há avanços consistentes em estimação de pose de objetos e robôs sob água, incluindo adaptação de domínio sim-to-real (tradução de dados sintéticos para estilo subaquático realista), redes tolerantes à turbidez, marcadores fiduciais robustos (linha Deep ChArUco / DeepArUco++) e marcadores ativos, além de calibração refrativa. Esse corpo trata, majoritariamente, do rastreamento de veículos (ROV/AUV) ou de objetos genéricos de manipulação submarina.

2. **Reconstrução ultrassônica de alta qualidade para END (S-scan, TFM, CPWC).** Há sofisticação algorítmica acústica considerável, mas com dependência crítica do conhecimento preciso da posição de aquisição — historicamente suprido por scanners eletromecânicos rígidos.

**A lacuna.** Não se identifica na literatura a integração explícita de estimação de pose 6DoF **subaquática** — baseada em *keypoints* densos (estilo PVNet) e/ou marcadores fiduciais profundos — voltada especificamente ao **registro espacial tridimensional** de imagens de END (S-scan/TFM/CPWC), com validação experimental. Os esforços existentes tratam ou do sensor robótico movendo-se no espaço (sem o vínculo com a formação da imagem ultrassônica), ou do rastreamento de sondas de END no seco (tipicamente aeroespacial, sobre compósitos, sem as degradações do meio aquático). A interseção "turbidez + registro de imagem de ultrassom via rastreamento óptico profundo" é, até onde a revisão alcançou, ausente.

**Justificativa.** Preencher essa lacuna tem relevância científica e prática. Cientificamente, articula-se um pipeline heterogêneo (visão profunda + acústica) sob restrições físicas do meio aquático, com um protocolo de validação métrica rigoroso. Praticamente, viabiliza-se a inspeção a mão livre ou por ROV em geometrias e locais inacessíveis a crawlers, reduzindo massa, custo e rigidez operacional. O uso do próprio sistema eletromecânico como referência de validação confere ao trabalho uma âncora experimental robusta e honesta: mede-se o sistema candidato contra exatamente aquilo que ele pretende substituir.

---

## 4. Hipóteses de Pesquisa

**Hipótese central (H₀).** A estimação visual da pose 6DoF do transdutor ultrassônico, combinada a um método de reconstrução de imagens de ultrassom, permite reduzir a dependência de encoders eletromecânicos em inspeções subaquáticas por END e melhorar (ou, no mínimo, preservar dentro de tolerância especificada) o registro espacial dos sinais adquiridos.

**Hipóteses específicas.**

- **H₁.** A combinação de estimação por *keypoints* densos (estilo PVNet) com detecção fiducial profunda (estilo Deep ChArUco) fornece estimativa de pose 6DoF mais robusta, sob turbidez e oclusão crescentes, do que qualquer uma das duas estratégias isoladamente.
- **H₂.** A aplicação de calibração refrativa explícita reduz significativamente o erro métrico de pose em relação ao uso do modelo *pinhole* com distorção radial padrão.
- **H₃.** A incorporação de dados sintéticos com adaptação de domínio ao conjunto de treinamento melhora a acurácia de pose em dados reais de tanque, mitigando o custo de anotação manual de *ground truth*.
- **H₄.** O registro espacial 3D das imagens de ultrassom, guiado pela pose visual estimada, atinge erro de posicionamento compatível com o obtido via referência eletromecânica, dentro de uma tolerância a ser especificada (e apropriada à resolução da técnica ultrassônica empregada).

Cada hipótese específica é diretamente testável por um ou mais experimentos formulados na Seção 7, com métricas definidas na Seção 8.

---

## 5. Objetivos

### 5.1. Objetivo geral

Desenvolver e validar experimentalmente, em ambiente controlado de tanque de laboratório, um pipeline de estimação visual de pose 6DoF de um transdutor ultrassônico e de registro espacial tridimensional das imagens de ultrassom por ele geradas, robusto às degradações ópticas do meio subaquático, capaz de reduzir a dependência de odometria eletromecânica em inspeções por END.

### 5.2. Objetivos específicos

1. Projetar e caracterizar o aparato experimental (tanque, câmera com *housing*, iluminação, conjunto transdutor/braçadeira/marcadores, amostra de tubulação e sistema de referência eletromecânico) e estabelecer o protocolo de calibração refrativa da câmera.
2. Construir um conjunto de dados subaquático rotulado com pose 6DoF de referência, combinando aquisições reais em tanque (com *ground truth* eletromecânico) e dados sintéticos renderizados a partir do modelo CAD do conjunto, submetidos a adaptação de domínio.
3. Implementar e treinar o módulo de estimação de pose por *keypoints* densos (estilo PVNet) e o módulo de detecção fiducial profunda (estilo Deep ChArUco), bem como a estratégia de fusão entre ambos.
4. Avaliar quantitativamente a acurácia e a robustez da pose estimada em função de níveis controlados de turbidez e de oclusão, comparando as estratégias isoladas e fundida contra a referência eletromecânica.
5. Implementar o módulo de registro espacial 3D, que transforma cada imagem de ultrassom para o referencial da peça segundo a pose estimada, e avaliar o erro de registro resultante.
6. Conduzir estudos de ablação para isolar a contribuição de cada componente (calibração refrativa, realce de imagem, dados sintéticos, fusão) sobre o desempenho final.
7. Documentar limitações, condições de falha e recomendações para transição do ambiente controlado de tanque para cenários de inspeção mais realistas (trabalho futuro).

---

## 6. Materiais e Métodos

### 6.1. Visão geral do pipeline

O pipeline organiza-se em duas fases sequenciais, conforme a delimitação acordada:

**Fase 1 — Estimação de pose 6DoF (núcleo da dissertação).**
Entrada: sequência de imagens subaquáticas do conjunto transdutor/braçadeira; parâmetros de calibração (intrínsecos e refrativos) da câmera; modelo CAD do conjunto; e, quando presentes, marcadores fiduciais fixados ao conjunto.
Processamento: (i) pré-processamento opcional de realce de imagem; (ii) estimação de *keypoints* por votação densa (estilo PVNet) e detecção fiducial subpixel (estilo Deep ChArUco); (iii) resolução da pose por PnP robusto sobre os pontos-chave e/ou cantos fiduciais; (iv) fusão das duas fontes de pose, com estimativa de incerteza associada.
Saída: sequência temporal de poses 6DoF do transdutor relativas à peça, preferencialmente acompanhada de incerteza.

**Fase 2 — Registro espacial tridimensional (escopo restrito).**
Entrada: imagens de ultrassom **já reconstruídas** (A-scan/B-scan/C-scan ou S-scan/TFM/CPWC, fornecidas prontas ao pipeline); sequência de poses 6DoF da Fase 1; parâmetros geométricos do transdutor.
Processamento: transformação rígida de cada imagem para o referencial tridimensional da peça, segundo a pose correspondente, e composição em uma representação volumétrica registrada.
Saída: conjunto de imagens de ultrassom espacialmente registrado em 3D sobre o modelo da peça.

Explicita-se que a Fase 2 **não** realiza reconstrução de imagem; um eventual pós-processamento das imagens que leve em conta a pose (por exemplo, refocalização) fica registrado como sugestão de trabalho futuro, fora do escopo desta dissertação.

### 6.2. Aparato experimental — o tanque de laboratório

A validação será integralmente conduzida em tanque de laboratório do LASSIP, ambiente que oferece controle sobre as variáveis de degradação (turbidez, iluminação, geometria) e, sobretudo, acesso a uma referência de pose confiável. Os componentes do aparato:

- **Tanque.** Reservatório com água, dimensionado para acomodar a amostra de tubulação, o conjunto transdutor/braçadeira, o sistema de posicionamento e o campo de visão da(s) câmera(s). Recomenda-se documentar dimensões internas, material das paredes e presença de janelas ópticas, pois esses fatores afetam reflexões e o percurso óptico.
- **Amostra de tubulação de aço.** Segmento de tubulação representativo, posicionado no interior do tanque, servindo simultaneamente como alvo geométrico da inspeção e como referencial da peça para o registro espacial. Idealmente, a amostra deve conter descontinuidades conhecidas (naturais ou usinadas — entalhes, furos de fundo plano) que permitam avaliar a fidelidade do registro final.
- **Conjunto transdutor/braçadeira.** O transdutor ultrassônico montado em uma braçadeira, cujo modelo CAD é conhecido e servirá de base para a definição dos pontos-chave 3D (Fase 1). A braçadeira também é o suporte físico dos marcadores fiduciais.
- **Marcadores fiduciais.** Tabuleiro(s) ChArUco fixado(s) rigidamente à braçadeira, com posição e orientação conhecidas em relação ao referencial do transdutor (a transformação braçadeira→marcador deve ser medida ou calibrada). Avaliar-se-á, como variante, o uso de marcadores ativos (autoiluminados) para mitigar *backscatter*.
- **Câmera e *housing*.** Câmera com resolução, taxa de quadros e óptica adequadas, alojada em *housing* submersível com janela plana (*flat port*) — configuração que impõe calibração refrativa. Registrar modelo, resolução, distância focal, abertura e características da janela.
- **Iluminação.** Fonte de iluminação controlada, cuja intensidade e geometria serão variáveis experimentais (a iluminação frontal intensa aumenta o *backscatter*; estratégias de iluminação lateral ou marcadores ativos serão contrastadas).
- **Sistema de posicionamento e referência de *ground truth*.** Este é o elemento metodologicamente crítico. O sistema eletromecânico existente (scanner motorizado / encoder / braço de cinemática conhecida) será empregado para mover o transdutor por trajetórias conhecidas e, simultaneamente, fornecer a **pose de referência** contra a qual a pose visual será comparada. Dessa forma, o dispositivo que o trabalho pretende, no longo prazo, substituir, cumpre no laboratório o papel de padrão-ouro de validação. A transformação entre o referencial do sistema de posicionamento e o referencial da câmera/peça deve ser cuidadosamente calibrada (calibração mão-olho, *hand-eye calibration*), sob pena de contaminar toda a avaliação com um erro sistemático de referencial.

### 6.3. Controle de turbidez

Para avaliar robustez de forma reprodutível, a turbidez da água será variada em níveis controlados e mensuráveis. Propõe-se o uso de um agente espalhador introduzido em quantidades dosadas, com a turbidez resultante medida em unidades nefelométricas (NTU) por turbidímetro, de modo que cada nível seja repetível entre sessões. A escolha do agente (por exemplo, suspensões padronizadas para calibração de turbidez, ou agentes de espalhamento de uso laboratorial consolidado) deve priorizar homogeneidade, estabilidade temporal durante a aquisição e ausência de agressão aos equipamentos. Registrar-se-á a curva de desempenho de cada módulo em função do NTU.

### 6.4. Controle de oclusão

A robustez à oclusão será avaliada obstruindo-se parcialmente o campo de visão do conjunto transdutor/braçadeira de maneira controlada e quantificável (por exemplo, cobertura percentual crescente do alvo por anteparo físico ou por posicionamento que force truncamento pela borda da imagem). O percentual de oclusão torna-se, assim, uma segunda variável independente de degradação, complementar à turbidez.

### 6.5. Construção do conjunto de dados

O treinamento dos módulos de aprendizado profundo demanda dados rotulados com pose 6DoF — grandeza cuja anotação manual é inviável e cujo *ground truth* real é custoso. A estratégia combina três fontes:

1. **Dados reais de tanque.** Aquisições em tanque, com a pose de referência fornecida pelo sistema eletromecânico, cobrindo variação de trajetória, distância, ângulo, iluminação, turbidez e oclusão. Constituem o conjunto de validação e teste primário, além de parte do treinamento.
2. **Dados sintéticos.** Renderização do modelo CAD do conjunto transdutor/braçadeira sob variação de pose, iluminação e parâmetros de câmera, com *domain randomization*, e simulação de efeitos subaquáticos (dominante cromática, véu por espalhamento, atenuação). A pose de cada amostra sintética é conhecida por construção, eliminando o custo de anotação.
3. **Adaptação de domínio (sim-to-real).** Tradução do estilo das imagens sintéticas para a aparência subaquática realista (por abordagens de tradução de imagem do tipo CycleGAN / Mask-CycleGAN, conforme literatura), reduzindo a lacuna de domínio entre o sintético e o real de tanque.

A proporção e a estratégia de mistura entre essas fontes, bem como a partição treino/validação/teste (garantindo separação estrita de trajetórias e condições entre partições, para evitar vazamento), serão documentadas e submetidas a estudo de ablação (H₃).

### 6.6. Implementação dos módulos

- **Módulo de *keypoints* densos (estilo PVNet).** Definição dos pontos-chave 3D sobre o modelo CAD do conjunto (por exemplo, por seleção que maximize dispersão espacial); treinamento da rede para predizer, por pixel, os vetores de votação; votação robusta; PnP para recuperação da pose.
- **Módulo fiducial (estilo Deep ChArUco).** Detecção dos pontos do tabuleiro ChArUco por rede dedicada, com refinamento subpixel dos cantos; PnP sobre os cantos, usando a geometria conhecida do tabuleiro e a transformação braçadeira→marcador.
- **Fusão.** Combinação das duas estimativas de pose, ponderada por incerteza/confiança de cada fonte (por exemplo, priorizando o fiducial em turbidez extrema, quando disponível, e os *keypoints* densos sob oclusão do marcador). A formulação exata da fusão (seleção, média ponderada, filtragem temporal) será objeto de experimentação (H₁).
- **Calibração refrativa.** Estimação dos parâmetros das interfaces refrativas e correção do modelo de projeção, aplicada previamente a ambos os módulos (H₂).
- **Realce de imagem (opcional).** Etapa de pré-processamento cuja ativação é variável de ablação.

### 6.7. Implementação do registro espacial 3D (Fase 2)

Recebidas as imagens de ultrassom prontas e a sequência de poses, cada imagem é posicionada no referencial da peça pela transformação rígida correspondente (composta a partir da pose do transdutor e da geometria conhecida do plano de imagem do ultrassom relativo ao transdutor). A composição das imagens transformadas produz a representação 3D registrada. A avaliação do registro (Seção 8) mede o quão fielmente descontinuidades conhecidas da amostra são posicionadas na representação final, contrastando o registro guiado por pose visual com o registro guiado pela pose de referência eletromecânica.

---

## 7. Protocolo Experimental

Os experimentos são formulados para testar, de maneira isolada e cumulativa, cada hipótese. Todos compartilham a mesma âncora de validação: a pose de referência eletromecânica.

### 7.1. Experimento 0 — Calibração e caracterização de linha de base

**Objetivo.** Estabelecer a calibração intrínseca, a calibração refrativa e a calibração mão-olho (referencial da câmera ↔ referencial do sistema de posicionamento ↔ referencial da peça), e caracterizar o erro residual do sistema de referência.
**Procedimento.** Aquisição de padrões de calibração sob água limpa; estimação dos parâmetros; quantificação do erro de reprojeção residual e do erro de fechamento da cadeia de referenciais.
**Saída.** Parâmetros de calibração validados e um orçamento de erro (*error budget*) da referência, indispensável para interpretar corretamente todas as comparações subsequentes.

### 7.2. Experimento 1 — Detecção fiducial vs. *markerless* sob turbidez crescente

**Hipótese testada.** Subsídio a H₁.
**Variáveis independentes.** Nível de turbidez (NTU), em água limpa e em degraus crescentes.
**Condições comparadas.** Detector ChArUco clássico (OpenCV) vs. detector fiducial profundo (estilo Deep ChArUco) vs. estimação por *keypoints* densos (estilo PVNet).
**Métricas.** Taxa de detecção/sucesso; erro de canto subpixel; erro de translação e de rotação da pose resultante.
**Resultado esperado.** Caracterização das faixas de turbidez em que cada estratégia mantém desempenho aceitável, evidenciando complementaridade.

### 7.3. Experimento 2 — Robustez à oclusão

**Hipótese testada.** Subsídio a H₁.
**Variáveis independentes.** Percentual de oclusão / grau de truncamento do alvo.
**Condições comparadas.** As mesmas do Experimento 1.
**Métricas.** Erro de pose (translação, rotação); taxa de falha de estimação.
**Resultado esperado.** Demonstração da tolerância superior dos *keypoints* densos à oclusão, contrastando com a sensibilidade do fiducial quando o marcador é obstruído — fundamentando a fusão.

### 7.4. Experimento 3 — Efeito da calibração refrativa

**Hipótese testada.** H₂.
**Variáveis independentes.** Modelo de calibração (pinhole + distorção radial vs. modelo refrativo explícito).
**Condições.** Trajetórias controladas em turbidez fixa (baixa/moderada), com pose de referência.
**Métricas.** Erro de translação e de rotação; erro de reprojeção.
**Resultado esperado.** Redução estatisticamente significativa do erro métrico sob o modelo refrativo.

### 7.5. Experimento 4 — Contribuição dos dados sintéticos e da adaptação de domínio

**Hipótese testada.** H₃.
**Variáveis independentes.** Composição do conjunto de treinamento (somente real; real + sintético sem adaptação; real + sintético com adaptação de domínio; e, se viável, somente sintético adaptado).
**Métricas.** Erro de pose em conjunto de teste real de tanque; curva de desempenho em função da quantidade de dados reais rotulados (avaliação da economia de anotação).
**Resultado esperado.** Ganho de acurácia e/ou redução da necessidade de dados reais rotulados com a inclusão de dados sintéticos adaptados.

### 7.6. Experimento 5 — Estimação de pose fundida: avaliação integrada

**Hipótese testada.** H₁ (consolidação).
**Variáveis independentes.** Estratégia de estimação (keypoints isolado; fiducial isolado; fusão).
**Condições.** Varredura combinada de turbidez × oclusão, cobrindo o envelope operacional.
**Métricas.** Erro de translação (mm), erro de rotação (graus), métricas baseadas em modelo (ADD/ADD-S), taxa de sucesso sob limiar; tempo de inferência (viabilidade de tempo real).
**Resultado esperado.** Superioridade da fusão em robustez agregada ao longo do envelope, com desempenho temporal compatível com uso prático.

### 7.7. Experimento 6 — Registro espacial 3D (Fase 2)

**Hipótese testada.** H₄ e, por consequência, H₀.
**Procedimento.** Aquisição de uma varredura completa sobre a amostra de tubulação (com descontinuidades conhecidas), gerando imagens de ultrassom prontas e a sequência de poses (visual estimada e eletromecânica de referência, em paralelo). Registro 3D das imagens sob cada fonte de pose.
**Métricas.** Erro de posicionamento das descontinuidades conhecidas na representação 3D; discrepância entre o registro guiado por pose visual e o guiado por referência; consistência geométrica global.
**Resultado esperado.** Erro de registro sob pose visual dentro da tolerância especificada relativamente à referência eletromecânica, sustentando a viabilidade do sistema como substituto.

### 7.8. Estudos de ablação (transversais)

Isolamento incremental de componentes — (a) sem/com calibração refrativa; (b) sem/com realce de imagem; (c) sem/com dados sintéticos adaptados; (d) estratégias de fusão — para atribuir a cada componente sua contribuição marginal ao desempenho final. Os estudos de ablação sustentam a interpretação causal dos resultados e evitam atribuir a um único fator ganhos que resultam da combinação.

---

## 8. Métricas de Avaliação

**Estimação de pose (Fase 1).**
- Erro de translação: norma da diferença entre translação estimada e de referência, em milímetros.
- Erro de rotação: distância angular (geodésica em SO(3)) entre orientação estimada e de referência, em graus.
- Métricas baseadas em modelo: ADD (distância média entre pontos do modelo sob pose estimada vs. referência) e ADD-S (variante para objetos com simetria), reportando taxa de acerto sob limiar habitual (fração do diâmetro do objeto).
- Erro de reprojeção: distância em pixels entre projeções dos pontos-chave sob pose estimada e sob referência.
- Taxa de sucesso: fração de quadros com erro abaixo de limiares especificados.
- Tempo de inferência / taxa de quadros: viabilidade de operação em tempo real.

**Detecção fiducial.**
- Taxa de detecção/sucesso por condição de degradação.
- Erro de localização de canto subpixel.

**Registro espacial 3D (Fase 2).**
- Erro de posicionamento de descontinuidades conhecidas (mm).
- Discrepância entre registro por pose visual e por referência eletromecânica.
- Métrica de consistência/sobreposição volumétrica, quando aplicável.

**Robustez (transversal).**
- Curvas de degradação de cada métrica em função de turbidez (NTU) e de oclusão (%), permitindo delimitar o envelope operacional de cada estratégia.

---

## 9. Análise Estatística e Critérios de Sucesso

Cada experimento será repetido em múltiplas trajetórias e sessões, com relato de tendência central e dispersão (média, desvio-padrão, medianas e intervalos), e não apenas de valores pontuais. Comparações entre condições (por exemplo, refrativo vs. pinhole; fusão vs. isolado) serão submetidas a testes de significância apropriados ao desenho pareado/repetido, com relato de tamanho de efeito além do valor-p, evitando conclusões baseadas em diferenças estatisticamente detectáveis, porém praticamente irrelevantes.

**Critérios de sucesso (a serem quantificados com o orientador na reunião de validação).** O sucesso da dissertação será definido por: (i) demonstração de que a fusão supera as estratégias isoladas em robustez agregada (H₁); (ii) evidência de redução significativa de erro com calibração refrativa (H₂); (iii) evidência de benefício dos dados sintéticos adaptados (H₃); e (iv) obtenção de erro de registro 3D sob pose visual dentro de tolerância especificada frente à referência eletromecânica (H₄/H₀). As tolerâncias numéricas concretas serão fixadas à luz da resolução da técnica ultrassônica empregada e das exigências de rastreabilidade da aplicação.

---

## 10. Cronograma de Execução (proposto)

O cronograma abaixo é indicativo e deverá ser ajustado com o orientador. Assume-se a reunião de validação de resultados iniciais já agendada (8 de julho de 2026) como marco de calibração do plano.

| Etapa | Atividade | Duração estimada |
| :--- | :--- | :--- |
| E1 | Consolidação do aparato, calibração intrínseca/refrativa/mão-olho e caracterização da referência (Exp. 0) | 1–2 meses |
| E2 | Construção do conjunto de dados: aquisições reais em tanque + geração sintética + adaptação de domínio | 2–3 meses |
| E3 | Implementação e treinamento dos módulos (keypoints, fiducial) e da fusão | 2–3 meses |
| E4 | Experimentos 1–5 (pose): turbidez, oclusão, refração, dados sintéticos, fusão + ablações | 2–3 meses |
| E5 | Implementação e avaliação do registro espacial 3D (Exp. 6) | 1–2 meses |
| E6 | Análise consolidada, redação da dissertação e submissão de artigo | 2–3 meses |

Etapas E2–E4 admitem paralelismo parcial (a geração sintética e a implementação de módulos podem avançar enquanto se acumulam aquisições reais). A submissão de um artigo a congresso/periódico, conforme recomendação prévia do orientador de priorizar a publicação antes da redação final da dissertação, deve ser posicionada tão logo os resultados de pose (E4) estejam consolidados.

---

## 11. Resultados Esperados e Contribuições

**Contribuição principal.** Um pipeline validado experimentalmente que integra estimação visual de pose 6DoF subaquática (keypoints densos + fiducial profundo, com calibração refrativa e fusão) ao registro espacial tridimensional de imagens de END, demonstrando viabilidade como alternativa à odometria eletromecânica — conjunção ainda ausente na literatura.

**Contribuições secundárias.**
- Caracterização quantitativa do envelope operacional (turbidez × oclusão) de estratégias de estimação de pose no contexto específico de rastreamento de transdutor.
- Metodologia de validação que emprega o sistema eletromecânico como padrão-ouro, oferecendo uma comparação direta e honesta entre o candidato e aquilo que ele pretende substituir.
- Conjunto de dados subaquático rotulado com pose (real de tanque + sintético adaptado) e o respectivo protocolo de geração, potencialmente reutilizável.
- Evidência empírica sobre o valor marginal de cada componente (calibração refrativa, realce, dados sintéticos, fusão), útil para orientar trabalhos subsequentes.

**Desdobramentos futuros (fora de escopo).** Pós-processamento das imagens de ultrassom guiado pela pose (refocalização); transição do tanque para cenários de campo; incorporação de fusão inercial (VIO) para robustez temporal; e extensão a geometrias de peça mais complexas.

---

## 12. Riscos e Planos de Contingência

| Risco | Impacto | Mitigação / contingência |
| :--- | :--- | :--- |
| Erro sistemático na cadeia de referenciais (calibração mão-olho deficiente) contamina toda a avaliação | Alto | Priorizar Exp. 0; quantificar orçamento de erro da referência; repetir calibração e verificar fechamento antes de qualquer experimento de pose |
| Lacuna de domínio sim-to-real maior que o previsto degrada o benefício dos dados sintéticos | Médio | Aumentar peso de dados reais; refinar adaptação de domínio; tratar dados sintéticos como augmentação, não como substituto |
| Turbidez extrema inviabiliza a estimação *markerless* em faixas relevantes | Médio | Recorrer a marcadores fiduciais (inclusive ativos) nessas faixas; delimitar honestamente o envelope operacional como resultado |
| Restrição de tempo do mestrado | Médio | Escopo já enxuto (Fase 2 restrita a registro); paralelizar E2–E4; priorizar publicação após E4 |
| Disponibilidade de amostra com descontinuidades conhecidas para avaliar o registro | Médio | Planejar com antecedência a amostra (entalhes/furos usinados) junto à equipe do LASSIP (Kalid) |
| Reflexões e artefatos ópticos nas paredes/janelas do tanque | Baixo–Médio | Documentar geometria do tanque; controlar iluminação; posicionar câmera para minimizar reflexos |

---

## 13. Reprodutibilidade e Boas Práticas

Serão documentados: parâmetros de calibração, composição e partição do conjunto de dados (com separação estrita entre treino/validação/teste por trajetória e condição), sementes e hiperparâmetros de treinamento, versões de software, e condições físicas de cada sessão (NTU, iluminação, oclusão). O objetivo é permitir que terceiros — e o próprio laboratório em trabalhos futuros — reproduzam e estendam os resultados. Reitera-se, por fim, a diretriz de integridade bibliográfica: toda referência empregada na dissertação passará por verificação individual contra a fonte original, com confirmação de DOI, autoria e ano, em conformidade com a orientação recebida.

---

## 14. Referências

> **Aviso.** A lista abaixo reproduz as referências mapeadas no survey que fundamenta este delineamento. **Cada entrada deve ser reconfirmada contra a base original antes da inclusão na dissertação.** Recomenda-se fortemente uma verificação ativa (resolução de DOI e conferência de autoria/ano) de todas as referências, com atenção redobrada às publicações mais recentes (2025–2026), antes de qualquer citação em texto avaliado.

1. Peng, S. et al. (2019). *PVNet: Pixel-wise Voting Network for 6DoF Pose Estimation*. CVPR. DOI: 10.1109/CVPR.2019.00466. — Arquitetura basilar de votação densa por pixel para pose 6DoF, tolerante a oclusão e truncamento.
2. Hu, D. et al. (2019). *Deep ChArUco: Dark ChArUco Marker Pose Estimation*. CVPR. DOI: 10.1109/CVPR.2019.00863. — Detecção fiducial por aprendizado profundo (ChArUcoNet + RefineNet) em iluminação severamente precária.
3. Berral-Soler, R. et al. (2024). *DeepArUco++: Improved detection of square fiducial markers in challenging lighting conditions*. Image and Vision Computing. DOI: 10.1016/j.imavis.2024.105313. — Refinamento subpixel de cantos fiduciais sob desfoque e iluminação adversa.
4. Ordoumpozanis, K.; Papakostas, G. A. (2025). *Reviewing 6D Pose Estimation: Model Strengths, Limitations, and Application Fields*. Applied Sciences. DOI: 10.3390/app15063284. — Panorama comparativo de métodos de pose 6D.
5. Risholm, P. et al. (2021). *Underwater Marker-Based Pose-Estimation With Associated Uncertainty*. ICCVW (OceanVision). DOI: 10.1109/ICCVW54120.2021.00414. — Estimação de pose por marcadores sob turbidez, com incerteza associada (SINTEF).
6. Wei, Q. et al. (2024). *Enhancing Inter-AUV Perception: Adaptive 6-DOF Pose Estimation with Synthetic Images for AUV Swarm Sensing*. Drones. DOI: 10.3390/drones8090486. — Adaptação de domínio (CycleGAN) de dados sintéticos para pose 6D subaquática.
7. (Referência sobre) *FAFA: Frequency-Aware Flow-Aided Self-supervision for Underwater Object Pose Estimation* (2024). DOI: 10.1007/978-3-031-73021-4_21. — Treinamento autossupervisionado para pose subaquática, auxiliado por fluxo.
8. (Referência SINTEF/NTNU sobre) *6D Pose Estimation for Subsea Intervention in Turbid Waters* (2021). — Pose 6D por *keypoints* em ROV inspecionando painel submarino em águas turvas. **Verificar DOI/veículo (inconsistência detectada na fonte).**
9. Song, Y.-W. et al. (2026). *Active Fiducial Marker-Based Precise Underwater Positioning System for Industrial and Robotics Applications*. IEEE Access. DOI: 10.1109/ACCESS.2026.3654109. — Marcadores fiduciais ativos (autoiluminados) para posicionamento subaquático. **Verificar (publicação muito recente).**
10. Seegräber, F. et al. (2025). *A Calibration Tool for Refractive Underwater Vision*. ICCVW. DOI: 10.1109/ICCVW69036.2025.00218. — Ferramenta de calibração refrativa para múltiplas interfaces ar–vidro–água. **Verificar.**
11. (Referência sobre) *Optical Design and Polarization Analysis for Full-Polarization Underwater Imaging Lens* (2025). Photonics. DOI: 10.3390/photonics12050517. — Óptica e polarização para isolar alvos do espalhamento.
12. (Referência sobre) *Studies on Underwater Image Processing Using Artificial Intelligence Technologies* (2025). IEEE Access. — Revisão de redes profundas para restauração/realce de imagem subaquática. **Verificar DOI.**
13. Li, J. et al. (2025). *Robust underwater object tracking with image enhancement and two-step feature compression*. Complex & Intelligent Systems. DOI: 10.1007/s40747-024-01755-y. — Rastreamento robusto com realce e compressão de *features*.
14. Hożyń, S. (2021). *Stereo Vision System for Vision-Based Control of Inspection-Class ROVs*. Remote Sensing. DOI: 10.3390/rs13245075. — Pipeline de visão estéreo para controle de ROV de inspeção.
15. Robotics and Perception Group (Scaramuzza Lab), UZH. *Visual-Inertial Odometry and SLAM*. URL: rpg.ifi.uzh.ch. — Linha de referência fundacional em VIO/SLAM.
16. Huang, L. et al. (2025). *Real-Time Millimeter-Accurate Underwater Pose Estimation via Tightly-Coupled Fusion of Vision and Optical Tracking*. IEEE Robotics and Automation Letters. DOI: 10.1109/LRA.2025.3641116. — Fusão rigorosa visão + rastreamento óptico para pose submarina milimétrica. **Verificar.**
17. Heil, T. et al. (2023). *Localisation of Ultrasonic NDT Data Using Hybrid Tracking of Component and Probe*. Journal of Nondestructive Evaluation. — Registro espacial de dados de END por rastreamento híbrido, sem encoders restritivos.
18. Gomes, A. et al. (2025). *Matrix Probe Offset Calibration for Robotic Arm Scanning*. IEEE IUS. DOI: 10.1109/IUS62464.2025.11201695. — Autocalibração de offsets 6D via correlação do tempo de voo ultrassônico. **Verificar.**
19. (Referência sobre) *Adapting robot paths for automated NDT of complex structures using ultrasonic alignment* (2019). DOI: 10.1063/1.5099756. — Calibração posicional iterativa de PAUT acoplada ao modelo 3D da peça.
20. (Referência sobre) *Research on ultrasonic coherent plane-wave compounding imaging method* (2026). NDT & E International. — Avanços em CPWC/PAUT para reconstrução rápida. **Verificar DOI/ano.**

*(Numeração e formatação bibliográfica final — ABNT ou IEEE — a definir conforme norma do programa.)*
