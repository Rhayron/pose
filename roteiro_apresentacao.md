# Roteiro de apresentação, slide a slide

## Slide 1. Capa

Boa tarde a todos. Meu nome é Rhayron de Sousa Nogueira, sou mestrando do CPGEI da UTFPR, no laboratório LASSIP, sob orientação do professor Thiago Passarin. Hoje vou apresentar o delineamento da minha pesquisa de mestrado e os primeiros resultados exploratórios que já obtivemos. O título do trabalho resume as duas entregas centrais: estimação visual de pose 6DoF de um transdutor ultrassônico, ou seja, a posição e a orientação do transdutor no espaço, estimadas por câmera; e o registro espacial tridimensional das imagens de ultrassom geradas por esse transdutor, no contexto de inspeção subaquática por ensaios não destrutivos. Ao longo da apresentação vou mostrar o problema que motiva o trabalho, a lacuna na literatura, os objetivos, o escopo acordado com o orientador, o pipeline proposto, os experimentos exploratórios que já rodamos com dados reais de tanque e o plano dos próximos experimentos.

## Slide 2. Contexto e problema

Para situar todos: ensaios não destrutivos por ultrassom são a principal técnica para detectar defeitos internos em dutos e estruturas metálicas, como trincas e corrosão, sem danificar a peça. O ponto central deste slide é que a medição ultrassônica só tem valor pleno quando sabemos onde ela foi feita. Um eco que indica uma trinca não serve para decisão de manutenção se não conseguirmos dizer em que ponto da geometria da peça aquela trinca está. Isso se chama rastreabilidade espacial, e é ela que permite comparar inspeções ao longo do tempo e acompanhar a evolução de um defeito.

Hoje essa rastreabilidade é obtida acoplando ao transdutor dispositivos eletromecânicos: encoders, trilhos, correias magnéticas, braços robóticos. Esses aparatos funcionam, mas trazem quatro limitações: restringem o acesso a geometrias complexas; escorregam em superfícies molhadas ou incrustadas, acumulando erro; são pesados, caros e exigem manutenção; e prendem a inspeção a trajetórias pré-programadas, impedindo a inspeção à mão livre.

A alternativa que proponho é visual: uma câmera observa o transdutor e estima, quadro a quadro, sua pose completa, com seis graus de liberdade, três de translação e três de rotação. O desafio é que o ambiente subaquático degrada a imagem: turbidez, espalhamento de luz por partículas, que chamamos de backscatter, perda das cores, principalmente o vermelho, e a refração da luz ao atravessar as interfaces entre ar, vidro e água. A foto à direita mostra o nosso aparato real no tanque do LASSIP, onde os testes exploratórios foram feitos.

## Slide 3. Lacuna científica

A revisão de literatura que conduzi mostrou dois campos maduros, mas que não conversam entre si. O primeiro cartão é a visão computacional subaquática: existem trabalhos consistentes de estimação de pose 6DoF debaixo d'água, marcadores fiduciais detectados por redes neurais e calibração que modela a refração. Só que esse corpo de literatura foca em rastrear veículos, como ROVs e AUVs, ou objetos de manipulação, e não instrumentos de medição.

O segundo cartão é a reconstrução ultrassônica para ensaios não destrutivos: técnicas como S-scan com foco, TFM e CPWC, que são sofisticadas acusticamente, mas todas partem de uma premissa: a posição de cada aquisição precisa ser conhecida. E hoje quem fornece essa posição são justamente os scanners rígidos que queremos dispensar.

O terceiro cartão é a interseção: usar rastreamento visual profundo subaquático especificamente para registrar espacialmente imagens de ensaio não destrutivo, com validação experimental. Essa conjunção eu não identifiquei na revisão conduzida. E destaco a última linha do slide, que é um diferencial metodológico do trabalho: a validação usará o próprio sistema eletromecânico existente no laboratório como padrão-ouro. Ou seja, vamos medir o sistema candidato exatamente contra aquilo que ele pretende substituir.

## Slide 4. Objetivos

O objetivo geral, no quadro superior, é desenvolver e validar experimentalmente, em tanque de laboratório, um pipeline que estima a pose 6DoF do transdutor por visão e registra as imagens de ultrassom em três dimensões, de forma robusta às degradações ópticas da água.

Os objetivos específicos desdobram isso em seis entregas. Primeiro, caracterizar o aparato e estabelecer as três calibrações necessárias: a intrínseca da câmera, a refrativa, que modela o desvio da luz nas interfaces, e a chamada mão-olho, que relaciona o referencial da câmera com o do sistema de posicionamento; disso sai um orçamento de erro da referência, ou seja, quanto o nosso padrão-ouro erra. Segundo, construir o conjunto de dados: aquisições reais no tanque com ground truth eletromecânico e dados sintéticos renderizados a partir do CAD, com adaptação de domínio. Terceiro, implementar os dois estimadores de pose, que detalho nos próximos slides, e a fusão entre eles. Quarto, quantificar acurácia e robustez variando turbidez e oclusão de forma controlada, sempre contra a referência eletromecânica. Quinto, implementar o registro 3D e medir o erro de posicionamento usando defeitos conhecidos na amostra. E sexto, estudos de ablação, que isolam a contribuição de cada componente do pipeline, para sabermos o que de fato importa.

## Slide 5. Escopo da pesquisa

Este slide é importante porque delimita com precisão o que a dissertação entrega e o que ela não entrega, conforme acordado com o orientador.

Do lado verde, dentro do escopo: a Fase 1, que é a estimação da pose 6DoF do transdutor por visão computacional, e que é o núcleo da dissertação; e a Fase 2, que é o posicionamento espacial 3D das imagens de ultrassom. Um detalhe fundamental: essas imagens chegam prontas ao meu pipeline. A contribuição, como está escrita no cartão, é primeiro estimar onde o transdutor está e depois usar essa geometria para posicionar as imagens bidimensionais, gerando a representação tridimensional.

Do lado vermelho, fora do escopo: a reconstrução das imagens de ultrassom em si. O método de reconstrução fica deliberadamente em aberto: quando há lente acústica, o grupo utiliza varredura setorial S-scan com foco, com leis focais que consideram todas as refrações; sem lente, provavelmente TFM ou CPWC. Também está fora a formulação por problemas inversos, que não corresponde à abordagem do grupo, e o pós-processamento das imagens guiado pela pose, como refocalização, que fica registrado como estudo futuro.

Essa delimitação decorre das limitações de tempo do mestrado e garante que a pesquisa ataque uma variável de cada vez.

## Slide 6. Pipeline proposto

Aqui está a arquitetura completa do que será construído, nas duas fases.

Na Fase 1, da esquerda para a direita: a aquisição, com câmera em housing e as calibrações intrínseca e refrativa, porque a janela plana do housing viola o modelo de câmera convencional; uma etapa opcional de realce de imagem, correção de cor e remoção de véu, que será tratada como variável de ablação, ou seja, mediremos se ela ajuda ou não; em seguida os dois estimadores em paralelo, um por keypoints densos no estilo PVNet e outro por marcador fiducial profundo no estilo Deep ChArUco; depois a recuperação da pose por PnP, que é o algoritmo que resolve a pose a partir de correspondências entre pontos 3D conhecidos e suas projeções 2D, com fusão das duas fontes ponderada por incerteza. A saída é a pose 6DoF por quadro, rotação e translação, acompanhada de incerteza.

Na Fase 2: as imagens de ultrassom chegam prontas, produzidas pelos métodos consolidados do laboratório; cada imagem 2D sofre uma transformação rígida para o referencial da peça, usando a pose do instante em que foi adquirida; e a composição de todas gera a representação 3D registrada, avaliada com descontinuidades conhecidas da amostra.

Na linha de baixo está a âncora de validação de todo o trabalho: cada pose visual será comparada com a pose da referência eletromecânica.

## Slide 7. Fundamentação: PVNet

Agora os dois pilares técnicos da Fase 1. O primeiro é a PVNet, publicada por Peng e colaboradores na CVPR de 2019. A ideia central: em vez de detectar pontos de interesse diretamente, a rede prevê, para cada pixel que pertence ao objeto, um vetor unitário apontando para cada ponto-chave. A localização de cada ponto-chave é então obtida por votação: os vetores de todos os pixels são intersectados de forma robusta usando RANSAC, que descarta votos inconsistentes.

A imagem à direita mostra essas hipóteses de votação: as elipses indicam a distribuição das hipóteses para cada ponto-chave. A propriedade que nos interessa é a tolerância à oclusão: mesmo que metade do objeto esteja encoberta, os pixels visíveis continuam votando corretamente, inclusive em pontos-chave que estão na parte encoberta. Com os pontos-chave votados, a pose é recuperada por PnP, sem depender de textura natural do alvo, o que é relevante porque nosso transdutor e a braçadeira são objetos lisos e pouco texturizados.

No pipeline, esse ramo cumpre o papel de estimador sem marcador: é ele que deve manter a pose quando o marcador fiducial estiver ocluído, sujo ou ilegível.

## Slide 8. Fundamentação: Deep ChArUco

O segundo pilar é o Deep ChArUco, de Hu e colaboradores, também CVPR 2019. O diagrama, retirado do artigo original, mostra o pipeline: uma primeira rede, a ChArUcoNet, detecta os pontos do tabuleiro na imagem bruta; os patches em torno de cada detecção passam por uma segunda rede, a RefineNet, que refina a posição de cada canto com precisão subpixel; e os cantos refinados alimentam o PnP, que extrai a pose do marcador.

Por que substituir o detector clássico? Porque os detectores heurísticos, baseados em binarização e contornos, falham sob desfoque de movimento, sombras e baixo contraste; o detector aprendido mantém a operação nessas condições, que são exatamente as condições subaquáticas. Trabalhos posteriores, como o DeepArUco++, de Berral-Soler e colaboradores, melhoram ainda mais a detecção de cantos sob iluminação adversa, e há também a linha de marcadores ativos, autoiluminados, que reduz a dependência da iluminação externa, principal fonte de backscatter.

No pipeline, este ramo é a fonte de pose de alto contraste: um marcador de geometria conhecida fixado rigidamente à braçadeira do transdutor.

## Slide 9. Hipóteses

A pesquisa é organizada em quatro hipóteses testáveis, cada uma vinculada a experimentos e métricas pré-definidos no delineamento.

H1: a combinação dos dois estimadores, keypoints densos e fiducial profundo, é mais robusta sob turbidez e oclusão crescentes do que qualquer um deles isolado. A intuição é a complementaridade: o fiducial domina quando o marcador está visível; os keypoints seguram quando o marcador está ocluído.

H2: a calibração refrativa explícita, que modela fisicamente o caminho da luz pelas interfaces ar, vidro e água, reduz significativamente o erro métrico de pose em relação ao modelo pinhole com distorção radial comum. Sem isso, qualquer ganho de robustez das redes não se converte em acurácia em milímetros.

H3: dados sintéticos com adaptação de domínio melhoram a acurácia em dados reais e reduzem o custo de anotação, que para pose 6DoF é proibitivo de fazer à mão.

H4: o registro 3D guiado pela pose visual atinge erro compatível com o obtido pela referência eletromecânica, dentro de uma tolerância que será especificada em função da resolução da técnica ultrassônica. H4 é, na prática, o teste da hipótese central do trabalho.

## Slide 10. Insumos experimentais disponíveis

Antes dos resultados, o que temos de dados hoje. Em 27 de maio deste ano fizemos uma campanha exploratória no tanque do LASSIP, com apoio da equipe do laboratório. Dela saíram dois conjuntos pareados.

Primeiro, 13 vídeos em full HD a 60 quadros por segundo, com duração entre 8 e 19 segundos, filmados com a câmera fora do tanque, através da parede de vidro. Isso significa que o caminho óptico já inclui as refrações ar, vidro e água, o caso que a calibração refrativa terá de tratar.

Segundo, 12 aquisições ultrassônicas no formato m2k do sistema M2M. Cada uma é uma captura FMC completa, Full Matrix Capture, com 64 disparos vezes 64 elementos, amostrada a 125 megahertz, e indexada por tempo, 16 segundos, sem nenhum eixo de encoder. Ou seja, são varreduras genuinamente à mão livre: exatamente o cenário que a pose visual precisa resolver.

Na braçadeira há marcadores ArUco de dois dicionários, um 7 por 7 e um 5 por 5, e a amostra é um segmento de tubulação de aço, visível na foto.

A limitação desta campanha é declarada: não há ground truth sincronizado. Por isso estes dados sustentam exploração e desenvolvimento, não validação metrológica. A validação virá da campanha com referência eletromecânica.

## Slide 11. Exploratório 1: baseline do detector clássico

O primeiro experimento exploratório responde a uma pergunta que precisava de medição, não de suposição: quão bem o detector ArUco clássico do OpenCV funciona no nosso tanque?

Rodamos o detector em todos os 13 vídeos. Resultado: em 12 deles, detecção entre 98 e 100 por cento dos quadros. Em água limpa e boa iluminação, o detector clássico simplesmente funciona. Mas no vídeo de menor nitidez a taxa cai para 60 por cento, mostrando que a degradação existe e é mensurável no nosso próprio aparato. Além disso, os marcadores menores colados na braçadeira e no tubo nunca foram detectados pelo método clássico.

Também validamos o pipeline completo de ponta a ponta: vídeo, detecção, PnP e trajetória, com zero falhas de PnP em 126 poses estimadas. A imagem à direita mostra uma detecção real, com o marcador 7 por 7 em verde e o 5 por 5 em laranja.

A leitura científica deste resultado orienta todo o resto: em água limpa o detector clássico não é o gargalo. O ganho do detector profundo precisa aparecer, e vai aparecer, nos regimes degradados.

## Slide 12. Detecção de pose 6DoF nos dados reais do tanque

Este slide mostra a pose sendo de fato estimada nos nossos dados. Nas duas fotos, os eixos coloridos desenhados sobre o marcador representam a pose completa recuperada pelo PnP: a origem no centro do marcador e os três eixos de orientação. À esquerda, uma condição clara; à direita, uma condição escura. Em ambas o sistema resolve a pose.

Embaixo, a trajetória de uma varredura à mão livre reconstruída quadro a quadro: 71 poses de um dos vídeos. O gráfico da esquerda mostra o percurso no plano da imagem, com início em verde e fim em vermelho; o da direita mostra as três componentes da translação ao longo do tempo.

Uma ressalva importante, destacada em vermelho no slide: estas poses usam parâmetros intrínsecos nominais da câmera, porque a calibração ainda não foi feita. Portanto a escala é nominal, não métrica. Os valores em milímetros são indicativos de forma, não de medida. É justamente o Experimento 0, de calibração, que converterá estas trajetórias para milímetros reais. O que este slide demonstra é a viabilidade do caminho completo nos dados reais.

## Slide 13. Exploratório 2: detector profundo de cantos

Aqui está o primeiro treinamento de rede neural do projeto. Como não temos ground truth, usamos uma estratégia da literatura do DeepArUco: pseudo-rótulos. O detector clássico, que funciona muito bem em quadros limpos, rotulou 3.906 quadros automaticamente. Sobre esses quadros aplicamos degradação sintética agressiva durante o treino: escurecimento, borramento, véu de espalhamento simulando backscatter e ruído. Assim a rede aprende a detectar em condições onde o próprio rotulador falharia. A partição dos dados foi feita por vídeo, nunca por quadro, para impedir vazamento entre treino e teste; o teste usa dois vídeos que a rede nunca viu.

O gráfico compara as taxas de detecção por nível de degradação. Em limpo, todos empatam em 100 por cento. Conforme a degradação aumenta, o detector clássico, em cinza, despenca: 19,5 por cento no nível médio e 5,5 no severo, medidos em 200 amostras. A rede, em azul, mantém 66 e 30 por cento. Isso é um fator de mais de três vezes no nível médio. E onde detecta, a rede localiza os cantos com mediana em torno de 1 pixel.

O treino levou cerca de 19 minutos em uma GPU comum, o que mostra que o ciclo de experimentação é barato e repetível.

## Slide 14. Exploratório 3: rejeição de outliers por seleção de picos

Este slide traz duas lições, uma negativa e uma positiva, e faço questão de apresentar as duas.

A negativa: implementamos um refinador subpixel de segundo estágio e ele não funcionou. A investigação mostrou o porquê: o diagnóstico que motivou o refinador estava enviesado pela métrica média. A média do erro de canto era alta, na casa de 20 pixels, mas a mediana real já era de cerca de 1 pixel. O problema não era o caso típico: eram de 3 a 9 por cento de cantos catastróficos, com erro em torno de 90 pixels, quando a rede escolhe um pico errado, por exemplo um reflexo. Um refinador com alcance de 12 pixels não corrige um erro de 90. Resultado negativo documentado, e uma lição metodológica: diagnóstico exige olhar a distribuição do erro, não só a média.

A positiva: a solução correta não exigiu retreinar nada. Em vez de aceitar o pico mais forte de cada canto, extraímos os três picos mais fortes, montamos as combinações geometricamente plausíveis e validamos cada candidata decodificando os bits internos do marcador, que são conhecidos. Se nenhuma combinação decodifica, o quadro é rejeitado. O gráfico mostra o efeito: os cantos catastróficos caem de até 8,8 por cento para zero em todos os níveis. O custo é a rejeição de até 12 pontos percentuais de quadros, o que a 60 quadros por segundo é recuperável por filtragem temporal. Para o PnP, essa troca é claramente vantajosa: um quadro rejeitado não contamina a pose; um canto a 90 pixels destruiria a pose silenciosamente.

## Slide 15. Detecções da rede sob degradação

Estas são três detecções reais do sistema completo, rede mais seleção de picos, nos vídeos de teste, que a rede nunca viu no treino. Os dois primeiros exemplos estão no nível médio de degradação e o terceiro no severo. São condições em que o detector clássico praticamente não opera.

Em cada exemplo, o quadrilátero verde com cantos em laranja é o que o sistema detectou; as cruzes são o pseudo-rótulo de referência obtido do quadro limpo correspondente. Os quadriláteros coincidem com as cruzes, com erro mediano de cerca de 1 pixel, indicado no topo de cada imagem.

E destaco o número de decode em cada exemplo: cada detecção só é aceita se os bits internos do quadrilátero decodificarem como o marcador de identidade zero, que é o marcador que sabemos estar na braçadeira. Isso significa que a confiança de cada detecção não é uma probabilidade aprendida pela rede, e sim uma verificação física contra um padrão conhecido. Essa propriedade será valiosa na fusão da Fase 1, porque dá um critério objetivo para ponderar as fontes de pose.

## Slide 16. Síntese dos exploratórios

Consolidando o que os exploratórios estabeleceram. Primeiro número: 100 por cento do pipeline funcionando de ponta a ponta nos dados reais do tanque, de vídeo a trajetória. Segundo: zero por cento de cantos catastróficos após a seleção geométrica com validação por decodificação. Terceiro: três vírgula quatro vezes mais detecção que o método clássico sob degradação média. Quarto: mediana de localização em torno de 1 pixel, que é compatível com uso em PnP.

Com a mesma clareza, as limitações, na linha vermelha: a degradação usada é sintética, não é turbidez real medida em NTU; os pseudo-rótulos definem um teto de acurácia, porque a rede não pode ser melhor avaliada do que a qualidade dos rótulos; e não há ground truth metrológico nesta fase. Essas três limitações não são defeitos do trabalho: são exatamente o que a próxima fase experimental foi desenhada para tratar. Os exploratórios cumpriram seu papel: reduziram risco técnico, estabeleceram baselines medidas no nosso aparato e validaram as decisões de arquitetura antes dos experimentos caros.

## Slide 17. Próximos experimentos práticos

O plano prático, em ordem de dependência.

Item um, o Experimento 0, que é bloqueante: calibração intrínseca em ar, calibração refrativa da configuração câmera, vidro e água, e calibração mão-olho entre câmera, scanner e peça. Disso sai o orçamento de erro da referência. Nada com ground truth é adquirido antes disso, porque erro sistemático na cadeia de referenciais contaminaria todas as comparações.

Item dois, a campanha de aquisições com ground truth eletromecânico: matriz de trajetórias, iluminação, turbidez e oclusão, com sincronização entre câmera e scanner por LED visível no quadro.

Item três, turbidez real em degraus medidos em NTU com turbidímetro, substituindo a degradação sintética pela física e gerando as curvas de desempenho por nível.

Item quatro, o CAD da braçadeira, que destrava a renderização sintética com pose exata e o treino do ramo PVNet, testando a hipótese H3.

Item cinco, a comparação com o DeepArUco++ pré-treinado, uma decisão de construir versus adotar, tomada com medição.

E item seis, a fusão das duas fontes de pose e o registro 3D com defeitos conhecidos, fechando H1 e H4.

## Slide 18. Referências

Estas são as referências citadas na apresentação, nas normas da ABNT: os dois artigos fundadores das arquiteturas que adotamos como base, PVNet e Deep ChArUco, ambos da CVPR de 2019; o DeepArUco++, de 2024, que estende a detecção fiducial para iluminação adversa; e os trabalhos de estimação de pose subaquática com marcadores e de calibração refrativa.

Registro uma prática do projeto: toda referência passa por verificação individual de DOI, autoria e ano contra a fonte original antes da versão final da dissertação.

Com isso encerro. Em resumo: o problema é dar rastreabilidade espacial à inspeção ultrassônica subaquática sem depender de aparato eletromecânico; a proposta é um pipeline de pose visual robusto ao meio aquático que posiciona em 3D imagens de ultrassom entregues prontas; os exploratórios já demonstraram o pipeline funcionando em dados reais e um detector que opera onde o clássico falha; e o próximo passo é a calibração e a campanha com ground truth, que transformam esses resultados em números metrológicos. Obrigado. Fico à disposição para perguntas.
