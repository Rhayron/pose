# Recaptura da intrínseca 4K

Só rode esta sessão se o foco, o anel de FOV (40–73°) ou a distância câmera–parede
mudaram. O `K` atual (2026-09-01, RMSE 0,599 px) já vale para 3840×2160.

## 0. Antes de ligar

- [ ] Tabuleiro ChArUco do contrato (`saida/tabuleiro.json`): 7×5, 34,0 mm, rígido e plano.
- [ ] Paquímetro no quadrado. Se não der 34,0 mm, regenere com `gerar_tabuleiro.py`.
- [ ] `python teste_caliscope.py` passando.
- [ ] Autofoco off; não mexer no FOV durante a sessão.

## 1. Modo

**3840×2160, MJPEG, 30 fps.** Outro modo → `aceitar_captura.py` recusa.

## 2. Gravar

```
calibracao/gravar_ffmpeg_s600.cmd
```

Preview 1280×720 + cópia MJPEG. `q` no terminal do ffmpeg para. Não use SkellyCam
(4K estoura RAM).

## 3. Aceitar e calibrar

```bash
python aceitar_captura.py
```

Caliscope 0.11.3 no `caliscope-workspace`. Intrinsics → cam **0** → Autocalibrate.
RMSE > 0,80 px → recaptura, não relaxa o critério.

## 4. Importar

Atualize os TOML em `origem_caliscope/` e os hashes em `caliscope-import.json`,
depois:

```bash
python caliscope_cli.py importar --config caliscope-import.json --output rig/caliscope-import.json --overwrite
python caliscope_cli.py ativar rig/caliscope-import.json --destino perfis_ativos/s600.json --overwrite
```

## Campanha de tanque

Para vídeo + ultrassom, **não** é esta sessão. Use `aquisicao/gravar.py`
(HANDOFF.md).
