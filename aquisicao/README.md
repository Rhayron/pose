# Aquisição sincronizada

App de apoio para gravar vídeo da S600 alinhado com a aquisição de ultrassom.

```bash
pip install pynput pillow
cd aquisicao
python gravar.py
```

## Fluxo

1. **PREPARAR → PRONTO**: abre a câmera no modo calibrado (3840×2160 MJPEG 30 fps pedido), trava foco e exposição e aguarda o primeiro quadro estável. Nada é gravado durante a preparação. Nesta USB o fps *medido* fica ~21 — o JSON registra `fps_medido`, não o valor pedido.
2. **ARMAR**: abre o vídeo e assina a fonte **antes** de ativar o listener global. A partir daqui o pré-roll é gravado de verdade no próprio `.avi`.
3. **Clique externo → GRAVANDO**: clique em START no software de ultrassom. O clique só carimba o instante no vídeo já aberto; não reabre nem inicia a câmera. Cliques dentro da janela do app são ignorados.
4. **PARAR → SALVANDO → SALVO**: fecha o vídeo, calcula o hash e publica os metadados. Aguarde a confirmação de sessão salva antes de considerar a operação concluída.

Em **ARMADO**, use **DESARMAR** ou `Escape` para remover explicitamente o pré-roll temporário e voltar a PRONTO. O botão Cancelar tem o mesmo efeito nesse estado. O fechamento durante SALVANDO é bloqueado até vídeo e metadados serem confirmados; durante GRAVANDO, a opção recomendada é salvar e fechar, e descarte exige confirmação explícita.

O preview mantém proporção 16:9 e desenha a ROI de sincronismo (com brilho) quando configurada. Ao lado, os cartões de preflight significam:

- **Integridade da gravação**: a câmera abriu no modo exigido e já entregou o primeiro quadro; uma ROI inválida impede a preparação.
- **Sincronismo**: sem ROI, há apenas clique e o nível será grosseiro; com ROI válida, ela torna possível medir um evento físico, mas o nível final depende de o degrau luminoso ser realmente detectado.
- **Validade métrica**: continua pendente enquanto transferência/refração e cadeia de referenciais não estiverem validadas; gravar não torna a sessão métrica.

Enquanto ARMADO ou GRAVANDO, a linha de saúde mostra telemetria ao vivo: duração, quadros recebidos, fps medido, ocupação/limite da fila e descartes. Ela serve para o operador perceber pressão de escrita, não para certificar qualidade científica.

## Por que a câmera não começa no clique

Abrir uma webcam USB custa centenas de milissegundos imprevisíveis: negociação DirectShow, primeiros quadros já velhos no buffer do driver, autoexposição assentando. Se a captura começasse no clique, toda essa latência entraria no sincronismo **sem ser medida**.

Capturando desde o PREPARAR, a câmera já está estável. Ao ARMAR, o escritor começa antes do listener global; portanto o clique apenas carimba um instante e os quadros anteriores são pré-roll real. A latência de partida não se mistura ao marcador.

## O que este sincronismo vale

Esta é a parte que não dá para varrer para debaixo do tapete.

| Nível | Quando acontece | Incerteza | Serve para |
| :--- | :--- | ---: | :--- |
| `ausente` | nem clique nem evento luminoso | não se aplica | nada |
| `grosseira` | **só o clique** | não medida, provavelmente 50–300 ms | alinhar trechos de trajetória com trechos de aquisição |
| `um_quadro` | luz de sincronismo no quadro | 1/`fps_medido` (~48 ms @ 21 fps) | associar pose a janelas curtas |
| `fina` | luz com quadro de transição parcial | ~1,7 ms | associar pose a A-scan individual |

O clique é um evento de interface. Entre ele e o primeiro disparo do pulser há a latência do software proprietário: desconhecida, provavelmente variável, impossível de medir do lado de cá. O JSON declara isso em `sincronismo.qualidade.nivel`, e o texto de `base` diz explicitamente o que aquele nível **não** autoriza.

Um alinhamento grosseiro declarado como grosseiro é utilizável. O mesmo alinhamento declarado como fino contamina tudo que vier depois.

### Quanto erro de posição um erro de tempo vira

Com o transdutor a `v` mm/s e erro de sincronismo `Δt`, o erro de posição é `v · Δt`. A 30 mm/s de varredura manual:

| `Δt` | erro de posição |
| ---: | ---: |
| 300 ms (clique, pior caso) | 9 mm |
| 100 ms (clique, caso bom) | 3 mm |
| 48 ms (um quadro @ ~21 fps) | 1,4 mm |
| 1,7 ms (interpolado) | 0,05 mm |

É esta tabela que decide se o clique basta para o seu experimento.

## Como subir para `fina`

Precisa de um evento comum **físico**: algo que apareça no quadro e seja acionado pelo mesmo sinal que dispara a aquisição. Uma luz no campo de visão resolve.

O `M2kConfig.xml` das suas aquisições mostra `modeAcquisitionSurTrigger="1"` e o codificador ativo `Temps` a 125 MHz. Se a caixa de aquisição tiver saída de sincronismo (a maioria dos sistemas M2M tem I/O configurável), uma luz acionada por ela dá o evento comum. Dois detalhes práticos:

- se a saída for um pulso curto por disparo, um LED ligado direto fica invisível porque o *duty cycle* é da ordem de 0,04%. Precisa de um esticador de pulso (monoestável retrigável ou um RC com transistor) para manter a luz acesa enquanto os pulsos chegam;
- a luz precisa ocupar uma região estável do quadro, sem reflexo do tanque em cima.

Com a luz montada, passe a região:

```bash
python gravar.py --roi 1700 40 160 120
```

O app desenha a ROI no preview e mostra o brilho ao vivo, para você conferir o enquadramento antes de gravar.

Validar a ROI só habilita a possibilidade de encontrar o evento comum físico. Não promove automaticamente `grosseira` para `um_quadro` ou `fina`: sem degrau detectável no vídeo, a sessão continua baseada apenas no clique.

### Alternativa sem eletrônica

Se a tela do equipamento aparecer no quadro, aponte a ROI para o indicador de aquisição. Dá `um_quadro` (1/`fps_medido`) e não custa nada, mas ocupa parte do enquadramento.

## Como a calibração entra na filmagem

**O vídeo não é corrigido.** Não há `undistort` nem `remap` em lugar nenhum: os quadros vão para o disco como o sensor entregou. A calibração viaja *junto*, como metadado, não *aplicada*.

Isso é deliberado. Corrigir distorção na gravação destrói informação de forma irreversível e prende a sessão a um modelo. Esse modelo ainda vai mudar, porque a calibração refrativa (H₂) é experimento em aberto. Gravando cru e guardando K/dist ao lado, dá para reprocessar com qualquer modelo depois, quantas vezes for preciso. O caminho contrário exigiria regravar o tanque.

O que o app faz com o perfil, em três níveis:

| | O quê | Se falhar |
| :--- | :--- | :--- |
| **Verifica o selo** | `carregar_perfil_ativo()` recalcula o SHA-256 do documento antes de ler K | erro: perfil adulterado não é carregado |
| **Impõe a resolução** | o driver tem de entregar exatamente 3840×2160 | erro duro: K vale para um modo só, não há reescala implícita |
| **Confere o foco** | compara o readback com o foco da calibração, e vigia se ele se mexeu durante a sessão | alerta na tela e no topo de `limitacoes` |
| **Registra a proveniência** | `import_id`, `activation_id`, `transferencia`, K, dist vão para o JSON | perfil `nao_validada` não impede gravar, mas o aviso viaja junto |

### Por que o foco tem tratamento especial

Foco é a única propriedade da câmera que muda a **geometria**. Exposição e ganho mexem em brilho e ruído; foco mexe em `fx` e `fy`. E nada na imagem denuncia: os quadros saem nítidos, a detecção de canto funciona normalmente, e o erro entra direto na escala, virando erro em milímetro sem nenhum sintoma visível.

Não existe tolerância defensável para essa comparação. As unidades de foco do DirectShow são arbitrárias e este projeto nunca mediu quanto K muda por unidade. Então qualquer diferença é relatada com a magnitude e a decisão fica com quem lê. O teste que de fato responde à pergunta é `validar_transferencia.py` rodado **naquele** foco.

Lembre que o driver da S600 frequentemente ignora `CAP_PROP_AUTOFOCUS=0` (readback 2). Foco constante num take não prova que o AF travou.

## Latência do pipeline

O carimbo de um quadro é tirado quando o driver o entrega, não quando o sensor expôs. Entre os dois há transferência USB, decodificação MJPEG e buffering, que somam dezenas de milissegundos.

Esse atraso é sistemático e **não cancela** quando comparado com o clique, que vem do relógio do sistema operacional sem esse atraso. Medir:

```bash
python medir_latencia.py --camera 0 --repeticoes 20
```

Aponte a câmera para a tela. O script pisca a tela em instantes conhecidos, com intervalos aleatórios para distribuir a fase, e mede em que quadro a mudança aparece. Depois:

```bash
python gravar.py --latencia-ms 42.5
```

O relatório traz a distribuição inteira, não só a média. Se a dispersão exceder um período de quadro, a latência não é constante e compensar por um número só introduziria erro variável. O relatório diz isso por escrito.

## O que o app registra

Cada sessão concluída gera `sessoes/<id>/video_<id>.avi` e `sessoes/<id>/sessao_<id>.json`. O schema é `pose.sessao_aquisicao` versão 2; o JSON final é publicado atomicamente, nunca como um documento pela metade. Ele traz:

- **carimbo de cada quadro** (monotônico), não só o instante inicial. Webcams USB perdem quadros e o fps medido pode ficar abaixo do pedido (nesta bancada, ~21 em vez de 30). Assumir taxa constante acumula erro;
- **estatísticas temporais**: fps medido, jitter RMS, quadros perdidos estimados pelo intervalo (não pela contagem nominal, que confunde perda com fps fora do nominal);
- **proveniência da calibração**: `import_id`, `activation_id` e o estado da transferência. Perfil `nao_validada` não impede gravar, mas o aviso viaja junto;
- **estado dos controles da câmera** antes, durante e depois, com o que o driver obedeceu e o que ignorou. Foco que se mexeu durante a sessão aparece aqui em vez de virar erro silencioso;
- **pré-roll** em `video.pre_roll`: presença, duração, instante inicial, marcador e quantidade de quadros escritos antes do clique; também registra os quadros mais próximos do marcador na captura e no vídeo;
- **`limitacoes`**: lista explícita do que aquela sessão não autoriza afirmar.

Se a finalização falhar, o vídeo é preservado deliberadamente e o app tenta publicar `sessao_<id>.incompleta.json`, também de forma atômica. Esse manifesto contém o erro e o estado `incompleta`, mas **não autoriza uso científico da sessão**.

## Verificação

```bash
python teste_aquisicao.py
```

Fonte sintética com temporização conhecida: o instante do evento é plantado por nós e o teste confere se o código recupera o número plantado. Inclui os casos que erram fácil: degrau abaixo do limiar não pode virar evento, e quadro perdido não pode quebrar a correspondência índice↔carimbo.

O detector de evento **não** usa `argmax(|diff|)`, e há teste para isso: com um quadro de transição parcial a sequência vira `baixo → intermediário → alto`, e o maior dos dois saltos é o segundo sempre que a luz acendeu na segunda metade da exposição. Apontar o maior salto erraria o quadro e perderia a interpolação. Os patamares vêm dos percentis 10 e 90, imunes a um único quadro intermediário.

## Arquivos

| Arquivo | Papel |
| :--- | :--- |
| `gravar.py` | App Tkinter: estados PREPARAR→PRONTO→ARMAR→GRAVANDO→PARAR/SALVANDO→SALVO, preview e preflight. |
| `camera.py` | Fonte de câmera: captura contínua, carimbo entre `grab()` e `retrieve()`, trava de automatismos com leitura de volta. |
| `sessao.py` | Escrita de vídeo em thread própria, detecção de evento luminoso, metadados. |
| `medir_latencia.py` | Mede a latência do pipeline pela tela. |
| `teste_aquisicao.py` | Testes com fonte sintética. |

## Limitações conhecidas

- O `pynput` é necessário para ver o clique que aciona o outro programa. Sem ele o app abre, mas o esquema de marcador não funciona.
- Se o start do ultrassom for numa tela que não é deste PC, o hook global não enxerga o clique. Nesse caso o único caminho é o evento luminoso.
- A validação da ROI verifica somente se ela cabe no quadro calibrado; ela não comprova montagem óptica, presença de luz nem sincronismo fino.
- O fechamento seguro evita perder uma finalização em curso, mas não remove as limitações de hardware: carimbo do driver não é instante de exposição, a latência USB/pipeline precisa ser medida, e a latência entre clique e pulser proprietário permanece desconhecida.
- O vídeo é gravado em MJPG. É recompressão sobre um MJPEG que já veio da câmera, então há perda dupla nas bordas de alto contraste que a detecção subpixel usa. Se isso incomodar na medição de canto, troque para um codec sem perdas (`--codec FFV1`) e aceite arquivos maiores.
