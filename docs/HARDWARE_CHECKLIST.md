# Checklist de hardware (em ordem de execução)

> Versão 1 (fim da Fase 2). As seções 4–7 serão completadas quando o modelo treinado e o harness estiverem integrados (Fases 4–7). **Nenhum número de latência deste projeto foi medido no ESP32 ainda**: tudo que depende da placa está marcado `PENDENTE (medir no hardware)`.

## 1. Fiação (ESP32 DevKit ↔ INMP441)

> ⚠️ **O INMP441 é alimentado com 3,3 V. Nunca ligue o VDD em 5 V.** Desligue a placa da USB antes de mexer na fiação.

| Sinal | Pino ESP32 | Constante em `firmware/include/board_config.h` | Observação |
|---|---|---|---|
| INMP441 VDD | **3V3** | — | 3,3 V |
| INMP441 GND | GND | — | |
| INMP441 L/R | GND | — | seleciona canal esquerdo |
| INMP441 SCK (BCLK) | GPIO 26 | `I2S_BCLK_PIN` | |
| INMP441 WS (LRCL) | GPIO 25 | `I2S_WS_PIN` | |
| INMP441 SD (DOUT) | GPIO 33 | `I2S_DIN_PIN` | |
| LED | GPIO 2 | `LED_PIN` | LED da placa; se usar LED externo: GPIO 2 → resistor 220 Ω → LED → GND |
| Buzzer (opcional) | GPIO 27 | `BUZZER_PIN` | buzzer **ativo**; habilite com `-DUSE_BUZZER=1` (padrão desligado) |

Fios curtos (< 15 cm) para I2S; fio longo no SCK gera ruído.

## 2. Gravar e rodar o autoteste

```bash
cd firmware
source ../.venv/bin/activate            # PlatformIO está instalado neste venv
pio run -e esp32-selftest -t upload     # grava (só depois de conferir a fiação)
pio device monitor -b 921600            # monitor serial
```

Esperado: o LED pisca 3 vezes; (com buzzer) um bip de 200 ms; depois, a cada 500 ms, uma linha como

```
raw min=-123456 max=130000 media=-350 | int16 dc=-5.3 rms=-52.1 dBFS [#####...............]
```

O LED da placa acende quando o nível passa de `RMS_GATE_DB` (−50 dBFS).

## 3. Como interpretar o autoteste

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `raw min=0 max=0` (**TRAVADO EM ZERO**) | SD sem conexão, VDD sem 3,3 V, ou canal errado | conferir SD (GPIO 33), VDD, GND; alternar `I2S_CHANNEL_SWAP` (0↔1) e regravar |
| leitura muda quando L/R vai para 3V3 | canal trocado | mantenha L/R no GND **e** use `I2S_CHANNEL_SWAP=1` se o zero persistir |
| `rms` sempre ≈ −90 dBFS mesmo batendo palma | sinal fraco: deslocamento grande demais | diminuir `I2S_SAMPLE_SHIFT` (ex.: 14 ou 12); há saturação nos extremos |
| aviso **SATURANDO** | deslocamento pequeno demais/som muito alto | aumentar `I2S_SAMPLE_SHIFT` |
| `rms` alto (> −20 dBFS) em silêncio, ruído enorme | fiação errada, fios longos, GND mal ligado | refazer GND e encurtar os fios |
| `dc` (offset) alguns milhares | normal no INMP441 | o firmware remove o DC em cada janela; nada a fazer |

Os valores brutos (`raw`) são palavras de 32 bits com 24 bits úteis nos bits 31..8; `I2S_SAMPLE_SHIFT = 16` os converte para `int16` (mesmo domínio dos WAVs de treino).
Ajuste as constantes em `board_config.h` **ou** com `build_flags = -DI2S_SAMPLE_SHIFT=14` no `platformio.ini`.

## 4. Calibrar `RMS_GATE_DB` e `PROB_THRESHOLD` na sala real

1. Com o autoteste, anote o `rms` do **silêncio da sala** (ex.: −65 dBFS) e do **alarme do celular a 30–50 cm** (ex.: −25 dBFS).
2. `RMS_GATE_DB` deve ficar ~10 dB acima do ruído de sala e bem abaixo do alarme. Ele vem de `ml/config.py` (`RMS_GATE_DB`); altere lá e rode `python -m ml.gen_headers` (não edite `dsp_config.h` à mão).
3. `PROB_THRESHOLD` é calibrado no treino (validação). Na sala, com `esp32-test`/monitor, veja a probabilidade das janelas do alarme. Se o alarme real do celular dá `prob` baixa de forma consistente, **não** mexa às cegas: registre os valores e discuta (pode ser necessário reforçar a augmentation de alto-falante/microfone).
4. *(PENDENTE, depende do modelo treinado — Fase 4.)*

## 5. Medir latência no hardware (preenche as tabelas do relatório)

```bash
cd firmware
pio run -e esp32-test -t upload
cd ..
python tests/run_test.py --target serial:/dev/ttyUSB0      # (Fase 5) troque a porta
```

O resultado (CSV/JSON/PNG, carimbado com `esp32`) vai para `docs/results/`. Até lá: **PENDENTE (medir no hardware)**.
Também dá para ler as estatísticas a cada 5 s no monitor serial do `esp32dev` (linhas `# t_sched ...`, `# t_feat ...`, `S,...`).

## 6. Roteiro de ensaio da demo (10 repetições)

1. Gravar `esp32dev`; abrir o monitor serial (921600) e **salvar o log** (`pio device monitor -b 921600 | tee demo.log`).
2. Tocar o alarme de fumaça (celular) a ~40 cm, 10 vezes; anotar na tabela abaixo se o LED acendeu e após quantos segundos.
3. Fazer 10 tentativas de **falso alarme**: palma, fala, chaves, toque de celular, sirene.
4. Anotar tudo. **PENDENTE (medir no hardware)**.

| # | Estímulo | LED acendeu? | Atraso (s) | Observação |
|---|---|---|---|---|
| 1 | alarme | | | |
| … | | | | |

**Plano B:** log da serial salvo; vídeo gravado do ensaio; cabo USB reserva; `esp32-test` + `tests/run_test.py --target native` rodando no notebook para mostrar o pipeline sem a placa.

## 7. O que preencher no relatório depois das medições reais

- `docs/relatorio_tecnico.md`, seção *Análise de latência*: tabela com média/p50/p95/máx de `t_sched`, `t_feat`, `t_queue`, `t_infer`, `t_total`, `t_decision` (hoje `PENDENTE`).
- Contadores `overruns`, `queue_drops`, `mutex_timeouts` e *stack high-water marks* (linha `S,...`).
- Acurácia ao vivo (tabela do item 6) e comparação com a acurácia do teste offline.
- Valores de `I2S_SAMPLE_SHIFT`, `I2S_CHANNEL_SWAP` e `RMS_GATE_DB` que funcionaram na sua placa.
