# Calibração intrínseca

A calibração deste projeto **não é medida aqui**. Ela é importada do projeto
`vrchat`, onde a mesma câmera física foi calibrada com Caliscope 0.11.3 em
2026-08-05, e depois **validada nesta bancada** antes de valer.

Este README explica as três coisas que essa frase esconde: por que importar,
por que a importação sozinha não basta, e o que foi aposentado.

## Por que a calibração própria foi aposentada

O pipeline anterior (`app.py` tkinter + `capturar.py` + `calibrar.py`) estava
correto no método e produziu um resultado **reprovado pelos próprios critérios
pré-registrados**, em 2026-07-29:

| Critério | Exigido | Medido | |
| :--- | ---: | ---: | :--- |
| vistas | ≥ 25 | 9 | reprova |
| cobertura completa | sim | 9/25 vistas, 0/4 escala média, 0/4 grande | reprova |
| RMS global | ≤ 0,50 px | 0,6124 px | reprova |
| P90 do erro de canto | ≤ 1,00 px | 0,9625 px | passa |
| erro mediano em holdout | ≤ 0,60 px | 0,5613 px | passa |
| largura relativa do IC 95% de `fx` | ≤ 2% | **61,5%** | reprova |

O último número é o que decide. Um IC 95% de `fx` indo de 1843 a 3625 significa
que a medição não distingue uma câmera de 67° de campo de uma de 40°. Não é uma
calibração ruim — é uma calibração que não mediu nada.

O caminho para corrigir seria capturar 25 vistas com cobertura completa. Só que
a mesma câmera já tinha sido calibrada corretamente sete dias depois, no outro
projeto, com ferramenta madura. Repetir a sessão seria refazer trabalho.

## Que a câmera é a mesma

O projeto anterior gravou apenas `{"indice": 0, "backend": "dshow"}` — sem nome
de dispositivo. A identificação foi feita pela assinatura óptica, que independe
de resolução:

| | `fx/largura` | FOV horizontal | distorção (k1, k2, k3) |
| :--- | ---: | ---: | :--- |
| pose, 2026-07-29, 3840×2160 | 0,7550 | 67,0° | +0,114, −0,410, +0,337 |
| **vrchat S600**, 1920×1080 | **0,7790** | **65,4°** | **+0,104, −0,450, +0,438** |
| vrchat C270, 1280×960 | 1,0856 | 49,5° | +0,007, **+0,374**, −0,865 |

A C270 tem `k2` de sinal oposto e 30% de diferença em `fx/largura`: é outra
lente. A S600 casa em sinal e magnitude nos cinco coeficientes, e a diferença de
3,1% em `fx/largura` cabe folgadamente dentro do IC 95% de ±61% da medição do
pose — os dois valores são estatisticamente indistinguíveis. Somando o índice
DirectShow 0 (que no gate do vrchat é a S600), a identificação é a EMEET
SmartCam S600, `stable_id` `USB\VID_328F&PID_00AD&MI_00\7&22EA2E16&0&0000`.

## Por que importar não basta

Mesma câmera não é mesma calibração. Três coisas mudam `fx, fy, cx, cy` e
nenhuma delas aparece no `camera_array.toml`:

1. **Foco.** O gate do vrchat observou foco em 200, 243, 254 e 281, com
   `autofocus=1`. O foco não estava travado.
2. **Campo de visão.** A S600 tem FOV ajustável de 40° a 73°
   ([EMEET](https://emeet.com/products/webcam-s600)). Nenhum dos dois projetos
   registra a posição desse ajuste.
3. **Resolução.** O intrínseco vale para 1920×1080 e só. A S600 também faz
   3840×2160@30, mas esse modo nunca foi calibrado — e escalar `K` por 2 assume
   que o recorte do sensor é idêntico, o que ninguém mediu.

Por isso o perfil importado nasce com `transferencia.status = "nao_validada"` e
`carregar_perfil_ativo()` **recusa** entregá-lo até que a medição na bancada
aprove. A hipótese não passa por dado em nenhum ponto do caminho.

## O gate de transferência

    H0: o par (K, dist) importado descreve a câmera nesta bancada.

Captura ~10 vistas ChArUco em 1920×1080, estima pose por `solvePnP` com **K e
dist congelados** — sem reajuste — e mede o resíduo de reprojeção.

### O critério que faz o trabalho

Resíduo de reprojeção **não detecta distância focal errada**. O `solvePnP`
absorve o erro de escala na profundidade: com `fx` 5% maior, ele estima o
tabuleiro 5% mais longe e o resíduo continua baixo. Medido em
`teste_caliscope.py`, com `fx` deliberadamente 5% errado:

| | medido | limite | |
| :--- | ---: | ---: | :--- |
| erro mediano | 0,171 px | 0,60 | passaria |
| erro P90 | 0,483 px | 1,20 | passaria |
| `escala_fx_refit` | 1,0496 | [0,98, 1,02] | **reprova** |

Um gate que só olhasse resíduo teria aprovado um foco 5% errado. Como o pose
estima pose 6DoF de um transdutor, 5% de erro de escala vira 5% de erro de
distância direto no resultado. `escala_fx_refit` reajusta **apenas** um fator
global sobre `fx/fy` e reporta a razão; o valor é diagnóstico e **nunca é
gravado** — escala fora da janela significa recalibrar no Caliscope, não
remendar o `K` importado.

### Critérios pré-registrados

    n_vistas          ≥ 10
    erro_mediano_px   ≤ 0,60      # o mesmo holdout que o pipeline anterior usava
    erro_p90_px       ≤ 1,20      # dobro da mediana, mesma razão P90/mediana de antes
    erro_max_px       ≤ 3,00
    frac_acima_1px    ≤ 0,20
    escala_fx_refit   ∈ [0,98, 1,02]   # mesma tolerância do IC 95% pré-registrado

Nenhum número foi escolhido depois de ver um resultado. A calibração de origem
mediu RMSE 0,533 px — uma transferência válida não pode sair muito pior que ela.

## Fluxo

```bash
# 1. Verificar o pipeline antes de medir qualquer coisa
python teste_caliscope.py

# 2. Importar e ativar (já feito; refazer só se a origem mudar)
python caliscope_cli.py importar --config caliscope-import.json \
                                 --output rig/caliscope-import.json --overwrite
python caliscope_cli.py ativar rig/caliscope-import.json \
                               --destino perfis_ativos/s600.json --overwrite

# 3. Capturar ~10 vistas ChArUco em 1920x1080 na bancada do pose,
#    com foco manual travado. Guardar em capturas_validacao/

# 4. Medir a transferência
python validar_transferencia.py --perfil perfis_ativos/s600.json \
                                --capturas capturas_validacao \
                                --output rig/transferencia.json --registrar

# 5. Provas independentes: retidão e distância com trena
python validar.py --calibracao perfis_ativos/s600.json \
                  --imagens capturas_validacao \
                  --distancia-real-mm 600 --imagem-distancia vista_03.png
```

O passo 5 não é redundante. `validar_transferencia.py` mede consistência
interna; `validar.py` confronta o milímetro estimado com um milímetro medido
com trena. É a única prova que ancora a escala no mundo.

## Arquivos

| Arquivo | Papel |
| :--- | :--- |
| `caliscope_import.py` | Importador. Sela o documento, recalcula todo hash do manifesto, aplica os critérios externos, mantém `transferencia` como estado explícito. |
| `caliscope_cli.py` | `importar` / `inspecionar` / `ativar`. Saída sempre JSON; código 0 aprova, 2 reprova. |
| `validar_transferencia.py` | O gate de H0. Reprojeção com K congelado + diagnóstico de escala. |
| `validar.py` | Provas independentes: reprojeção em sessão nova, retidão após undistort, distância contra trena. |
| `nucleo.py` | Fonte única do contrato do tabuleiro e da detecção. Calibrar e validar com tabuleiros diferentes é o erro silencioso clássico. |
| `gerar_tabuleiro.py` | Gera o ChArUco padrão e o `tabuleiro.json` que todo o resto lê. |
| `gerar_alvos_pose.py` | Alvos fiduciais para o transdutor. |
| `teste_caliscope.py` | Verifica que o gate aprova K certo **e reprova** K errado. |
| `caliscope-import.json` | Config da importação: origem, manifesto com SHA-256, bloco de aquisição. |
| `origem_caliscope/` | Artefatos do Caliscope copiados byte a byte do vrchat, com hash conferido. |
| `perfis_ativos/s600.json` | Perfil selado ativo. |
| `rig/` | Documento importado e relatório de transferência. |

## O tabuleiro é o mesmo objeto físico

`saida/tabuleiro.json` do pose e o do vrchat têm o mesmo SHA-256
(`f82d8fbb06bbd28d9c0087a3e75c84926b90daeffa83117a16214c473dcfec3a`): 7×5
quadrados, DICT_4X4_50, 34,0 mm medidos com paquimetro. O importador confere o
`intrinsic_charuco.toml` do Caliscope contra esse contrato e recusa a
importação se divergirem.

## Fronteira externa

O documento importado declara, por escrito, que:

- não contém nem alega evidência de validação interna;
- não alega a metodologia do calibrador próprio do pose;
- SHA-256 detecta alteração local, mas **não autentica operador nem origem**;
- o limite de RMSE de 0,80 px vale só para o caminho externo Caliscope. O
  limite do calibrador interno era 0,50 px e continua sendo o número de
  referência para qualquer calibração medida dentro do pose.

Dois documentos aprovados sob limites diferentes são distinguíveis pela leitura
do próprio arquivo, sem depender da memória de quem importou.

## Aposentado em 2026-08-07

Removidos: `app.py`, `capturar.py`, `captura_core.py`, `calibrar.py`,
`aceleracao.py`, `roteiro.py`, `iniciar_app.bat`, `teste_captura.py`,
`teste_loop.py`, `teste_e2e.py`, `teste_sintetico.py`, `capturas/` (147 MB),
`saida/calibracao_webcam_pc.json` e `saida/relatorio_webcam_pc.md`.

`teste_sintetico.py` saiu junto porque existia para exercitar `calibrar.py` por
subprocesso — sem o ajustador, testava um arquivo que não existe mais. O papel
dele, verificar o pipeline contra uma câmera de referência sintética antes de
medir, passou para `teste_caliscope.py`.

Tudo está no histórico do git (`0a0aeb5` e anteriores) se algum dia for preciso
recuperar a sessão de 2026-07-29.
