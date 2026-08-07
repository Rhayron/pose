# Guia da sessão de validação da transferência

Sessão curta: ~15 minutos. Não é uma calibração — os intrínsecos já vieram do
projeto `vrchat`. Aqui você só produz a evidência que decide se eles valem
nesta bancada. O porquê está em [`README.md`](README.md).

## 0. Antes de ligar a câmera

- [ ] Tabuleiro ChArUco impresso, colado em superfície **rígida e plana**.
      Papel ondulado vira erro de reprojeção que nenhum ajuste conserta.
- [ ] Quadrado medido com paquimetro. O contrato diz 34,0 mm — confira. Se o
      seu impresso deu outro valor, regenere com `gerar_tabuleiro.py`; não
      edite o JSON à mão.
- [ ] `python teste_caliscope.py` passando. Verifica o pipeline contra uma
      câmera sintética conhecida antes de você medir a real.

## 1. Modo da câmera

**1920×1080, MJPEG, 60 fps.** Não é preferência, é o único modo para o qual o
intrínseco importado vale. `validar_transferencia.py` reprova com falha dura se
as imagens vierem em outra resolução — não existe reescala implícita de `K`.

## 2. Travar o foco — o ponto mais importante

O gate do vrchat observou o foco da S600 variando entre 200 e 281, com
`autofocus=1`. Foco solto muda `fx` e `fy` continuamente.

- [ ] Desligue o autofoco no software da EMEET ou via `CAP_PROP_AUTOFOCUS=0`.
- [ ] Confirme lendo `CAP_PROP_FOCUS` de volta. Se o driver ignorar o comando,
      o valor lido não muda — e aí você **registra que não conseguiu travar**
      em vez de assumir que travou.
- [ ] Não mexa no ajuste de FOV da câmera (40°–73°) durante nem depois da
      sessão. Ele é digital e muda `fx` sem deixar rastro.

## 3. Capturar ~12 vistas

Mínimo 10; capture 12 para ter folga se alguma for descartada.

| Distribua entre | Alvo |
| :--- | :--- |
| células da grade 3×3 | pelo menos uma vista tocando cada célula |
| inclinação | metade frontal (< 15°), metade inclinada (15°–35°) |
| distância | varie de ~40 cm a ~1 m |

O tabuleiro precisa aparecer **inteiro** e nítido. Uma vista borrada rende
cantos deslocados que o gate lê como erro de calibração — e você perde tempo
investigando o `K` quando o problema era o foco daquele quadro.

Salve como PNG (sem perdas) em `capturas_validacao/`. JPEG introduz artefato de
compressão exatamente nas bordas de alto contraste que a detecção subpixel usa.

## 4. Medir

```bash
python validar_transferencia.py --perfil perfis_ativos/s600.json \
                                --capturas capturas_validacao \
                                --output rig/transferencia.json --registrar
```

`--registrar` grava o resultado dentro do perfil ativo e re-sela o documento.
Sem ele, você só vê o relatório e o perfil continua `nao_validada`.

## 5. Ler o veredicto

| `escala_fx_refit` | Resíduos | O que aconteceu |
| :--- | :--- | :--- |
| dentro de [0,98; 1,02] | dentro dos limites | **Aprovado.** H0 não foi rejeitada. Pode usar. |
| **fora** da janela | quaisquer | Foco ou FOV mudaram entre os projetos. Recalibre no Caliscope. **Não** corrija o `K` por esse fator. |
| dentro da janela | acima dos limites | O erro não está em `fx/fy`. Investigue nitidez, iluminação, planaridade do tabuleiro impresso. |

Critério que falha se corrige recapturando ou recalibrando — nunca relaxando o
número. Os limites foram fixados antes da primeira medição e estão gravados
dentro do próprio relatório.

## 6. Ancorar a escala no mundo

O passo 4 mede consistência interna: se `K` explica as imagens. Ele não sabe
quanto vale um milímetro. Para isso:

```bash
python validar.py --calibracao perfis_ativos/s600.json \
                  --imagens capturas_validacao \
                  --distancia-real-mm 600 --imagem-distancia vista_03.png
```

Meça com trena a distância do plano do tabuleiro à lente em **uma** das vistas
e passe o valor. É a única prova que confronta o milímetro estimado com um
milímetro do mundo — e a única que pega, de forma independente, um erro de
escala que o `solvePnP` esconde na profundidade.

## Se a transferência reprovar

Não é desastre e não invalida o trabalho. Significa que a câmera hoje não é a
câmera de 2026-08-05, e o caminho é uma calibração intrínseca nova no Caliscope
seguindo `GUIA_CALISCOPE.md` do projeto `vrchat` — gravar ~3 min de vídeo com o
tabuleiro cobrindo o campo, processar, exportar, e reimportar aqui apontando
`caliscope-import.json` para o novo `capture_volume`.

O importador, o gate e os critérios continuam os mesmos. Só a origem muda.
