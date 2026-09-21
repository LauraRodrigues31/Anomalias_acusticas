# Checklist de hardware (em ordem de execução)

> Versão final. **Latência e robustez do ESP32 foram medidas em 21/09/2026** (tabela da seção 5; execução de ≈ 28,6 min em silêncio com alarmes ocasionais, **não** o pior caso contínuo). Há só uma **amostra pequena** de resultados ao vivo (`docs/relatorio_tecnico.md`, seção 7); a tabela de 10 repetições (seção 6) e a acurácia ao vivo sistemática seguem `PENDENTE (medir no hardware)`. O firmware já contém o **modelo treinado** (limiar 0,9, voto 6 de 8).

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

O autoteste descarta o 1º bloco (o INMP441 leva ~250 ms para ligar e entrega zeros) e depois imprime a cada 500 ms: `raw min/max/media` (palavras de 32 bits, 24 bits úteis nos bits 31..8), `dc` (offset médio em `int16`), `pico`, `rms` em dBFS, se está acima/abaixo do gate (−50 dBFS), uma barra de nível e, quando reconhece um padrão de erro, uma linha `<< ...` com a causa provável. `I2S_SAMPLE_SHIFT = 16` converte para `int16` (mesmo domínio dos WAVs de treino); cada passo a menos no shift = **+6 dB** de ganho digital.

| Sintoma na serial | Causa provável | O que ajustar |
|---|---|---|
| `raw` só 0 e 1 (rms −180 dBFS) — `<< MICROFONE NAO ESTA ENTREGANDO DADOS` (**não é silêncio**: o INMP441 real em silêncio tem ruído de vários LSBs) | VDD sem 3,3 V, GND, SCK, WS, SD, L/R flutuando ou canal errado | conferir SD (GPIO 33), WS (25), SCK (26), VDD (3V3) e GND; L/R no GND; trocar `I2S_CHANNEL_SWAP` (0↔1) e regravar |
| `min` = `max` ≠ 0 — `<< AMOSTRAS CONSTANTES` | SD preso em nível fixo; sem clock (SCK/WS não chegam) | reconferir SCK/WS/SD, refazer os contatos (protoboard frouxa) |
| valores ≠ 0 mas o `rms` não sobe com palma (fica < −80 dBFS) — `<< nivel muito baixo` | ganho digital baixo demais ou canal errado | diminuir `I2S_SAMPLE_SHIFT` (14 ou 12); se continuar, `I2S_CHANNEL_SWAP` |
| `<< SINAL SATURADO`, `pico` ≈ 32767 | shift pequeno demais ou fonte muito perto | aumentar `I2S_SAMPLE_SHIFT`; afastar o celular |
| `rms` alto (> −10 dBFS) com a sala em silêncio — `<< nivel muito alto` | ruído de fiação: fios longos, GND ruim, VDD em 5 V | fios < 15 cm, GND comum, VDD em 3V3 |
| `dc` de milhares — `<< DC alto` | offset do INMP441 (normal) | nada; o firmware remove o DC em cada janela. Só se preocupe se vier com ruído alto |
| leitura muda quando o L/R vai para 3V3 | você está no canal errado | manter L/R no GND **e** usar `I2S_CHANNEL_SWAP` conforme o resultado do teste |
| alarme do celular fica **abaixo do gate** (`abaixo-do-gate`) | som fraco/longe; gate de −50 dBFS alto para o seu microfone | aproximar (30–50 cm), diminuir `I2S_SAMPLE_SHIFT` ou baixar o gate (seção 4); referência: 94 dB SPL ≈ −26 dBFS no INMP441 |
| autoteste não imprime nada / lixo | baud errado | `pio device monitor -b 921600` |
| upload falha ("Failed to connect") | GPIO 0/2 em nível errado no boot (LED externo/pull-up no GPIO 2) | soltar o LED externo do GPIO 2 durante a gravação; segurar BOOT se preciso |

Ajuste as constantes em `board_config.h` **ou** com `build_flags = -DI2S_SAMPLE_SHIFT=14` no `platformio.ini`. Auditoria do código I2S: pinos, `driver_install` → `set_pin` (ordem correta), formato 32 bits/`STAND_I2S`, `ONLY_LEFT`/`SWAP`, conversão com saturação e remoção de DC por janela estão conforme o esperado para Arduino-ESP32 2.0.x; **nada disso foi validado na placa**.

## 4. Calibrar `RMS_GATE_DB`, limiar e voto na sala real (sem regravar)

Com o `esp32dev` gravado (produção), os comandos `GATE`, `THR`, `VOTE`, `MON` e `STATS` (ver `docs/serial_protocol.md`) mudam os parâmetros **em RAM**; um reset volta aos padrões. Feche o monitor serial antes (a porta é exclusiva) e rode:

```bash
python tests/calibrate.py --port /dev/ttyUSB0 --label silencio --seconds 10
python tests/calibrate.py --port /dev/ttyUSB0 --label alarme   --seconds 20   # celular tocando o alarme a 30-50 cm
python tests/calibrate.py --port /dev/ttyUSB0 --label fala|palma|despertador --seconds 10
python tests/calibrate.py --suggest [--port /dev/ttyUSB0 --apply]
```

**Sessão guiada (recomendada quando sirene/despertador/toque disparam o alerta):**

```bash
python tests/calibrate.py --port /dev/ttyUSB0 --sessao            # 7 rótulos x 20 s; grava docs/results/calibracao_<data>.csv (não versionado)
python tests/calibrate.py --analisar docs/results/calibracao_<data>.csv   # refaz a análise sem a placa
```

Ela pede, um por vez, silencio, fala, palma_mesa, sirene, despertador, toque e alarme_fumaca ("toque X e aperte Enter"), coleta por `MON 1`, e imprime a probabilidade por rótulo e quantos ALERTAS cada combinação de `THR` {0,90; 0,95; 0,98; 0,99; 0,995} e `VOTE` {6/8, 7/8, 8/8, 10/12, 12/16} teria disparado. Recomenda a que mantém o alarme e minimiza os disparos; se nenhuma separa, diz isso e mostra a sobreposição das probabilidades. Para aplicar: `THR <p>` e `VOTE <n> <m>` no monitor serial (ou `--apply`, que só aplica se separar). Testada apenas contra o dispositivo simulado.

Cada coleta imprime p50/p95/máx de `rms_db` e da probabilidade e a fração de janelas acima do limiar; `--suggest` propõe `GATE`, `THR` e `VOTE` que não disparam nos sons negativos coletados e disparam no alarme (e avisa se isso não for possível). Referência: `RMS_GATE_DB` deve ficar ~6 dB acima do p95 do silêncio e bem abaixo do alarme. Para tornar permanente, o gate vem de `ml/config.py` (`python -m ml.gen_headers`) e limiar/voto do treino; **não** ajuste olhando o conjunto de teste. Valores atuais: limiar de treino `PROB_THRESHOLD = 0,9` (offline), **limiar ao vivo 0,99** no `esp32dev` (override `LIVE_PROB_THRESHOLD` em `board_config.h`, decisão D11), voto **6 de 8**, `RMS_GATE_DB = −50`. **Já feito ao vivo (21/09/2026):** a calibração de 20 s por som levou ao limiar **0,99** (`docs/decisions.md`, D11); o alarme chegou a probabilidade 0,998, ou seja, com folga estreita. **Ainda PENDENTE (medir no hardware):** repetir com outros volumes/distâncias/celulares e registrar as 10 repetições da seção 6.

## 5. Medir latência no hardware (preenche as tabelas do relatório)

```bash
cd firmware
pio run -e esp32-test -t upload
cd ..
python tests/run_test.py --target serial:/dev/ttyUSB0 --split val --max-per-type 10   # troque a porta
```

O resultado (CSV/JSON/PNG, carimbado com `esp32`) vai para `docs/results/`. O lado serial do harness **nunca rodou numa placa** (só contra `tests/fake_esp32.py`): se algo falhar, veja `docs/serial_protocol.md`. Sem `--fast` o envio é em tempo real (um clipe de 5 s leva ~5 s). O alvo serial do harness segue **não validado**; os números de latência abaixo vieram da linha de estatísticas do T4 no monitor serial do `esp32dev` (a cada 5 s ou por `STATS`).

**Medido no ESP32-D0WD-V3, firmware `esp32dev`, 21/09/2026, linha `# t=1714s` (n = 53.570 janelas, ≈ 28,6 min; silêncio com alarmes ocasionais, não o pior caso contínuo):**

| Etapa | média (µs) | p50 | p95 | máx |
|---|---|---|---|---|
| `t_sched` | 22 | 22 | 22 | 40 |
| `t_feat` | 1379 | 1377 | 1377 | 1603 |
| `t_queue` | 39 | 40 | 40 | 49 |
| `t_infer` | 10 | 9 | 11 | 153 |
| `t_total` (por janela) | 1452 | 1448 | 1450 | 1818 |
| `t_decision` (n = 25 alertas) | 178126 | 161558 | 225471 | 225471 |

`t_total` é o **processamento por janela** e **não** inclui a duração da janela (64 ms) nem o passo de 32 ms; compare-o com o orçamento de 32 ms (≈ 4,5% na média, ≈ 5,7% no máximo observado). Contadores: `overruns` = 0, `queue_drops` = 0, `torn_reads` = 0, `mutex_timeouts` = 0. Stack livre mínima (bytes): T1 = 3396, T2 = 3404, T3 = 2500, T4 = 4228. p50/p95 do T4 são sobre as últimas 512 janelas; média e máx, sobre todas.

Registro do bring-up: foi preciso **inverter `I2S_CHANNEL_SWAP` (0 → 1)**, e a gravação foi feita a **115200 baud** (`upload_speed`).

## 6. Roteiro de ensaio da demo (10 repetições)

1. Gravar `esp32dev`; abrir o monitor serial (921600) e **salvar o log** (`pio device monitor -b 921600 | tee demo.log`).
2. Tocar o alarme de fumaça (celular) a ~40 cm, 10 vezes; anotar na tabela abaixo se o LED acendeu e após quantos segundos.
3. Fazer 10 tentativas de **falso alarme**: palma, fala, chaves, toque de celular, sirene.
4. Anotar tudo. **PENDENTE (medir no hardware)** para as 10 repetições. Já observado, de forma informal (amostra pequena, com pouco registro; ver `docs/relatorio_tecnico.md`, seção 7): o alarme de fumaça foi tocado a partir de vídeos do YouTube em dois aparelhos (notebook: `demo_track.wav` com `aplay` e um vídeo; celular: teste final). No **celular** o LED acendeu, verificado **só visualmente** (sem log serial; número de repetições não registrado). Os tempos de decisão de ≈ 161 a 193 ms vêm de uma execução com log serial em que o **aparelho de origem do alarme NÃO foi registrado**. Distância de 30–50 cm **pretendida, não medida**. Com THR = 0,99, fala, palma, batida na mesa, despertador, toque e sirene não dispararam na calibração; folga estreita (alarme chegou a prob 0,998).

| # | Estímulo | LED acendeu? | Atraso (s) | Observação |
|---|---|---|---|---|
| 1 | alarme | | | |
| … | | | | |

**Plano B:** log da serial salvo; vídeo gravado do ensaio; cabo USB reserva; **se o microfone falhar**, grave o `esp32-test` e envie o áudio do alarme pelo USB: `python tests/run_test.py --target serial:/dev/ttyUSB0 --demo-clip <arquivo.wav>` (mostra a decisão janela a janela; ensaiado só contra o dispositivo simulado, **não validado na placa**); `esp32-test` + `tests/run_test.py --target native` rodando no notebook para mostrar o pipeline sem a placa.

## 7. O que preencher no relatório depois das medições reais

- `docs/relatorio_tecnico.md`, seção *Análise de latência* (tabela 6.2): **já preenchida** com a medição de 21/09/2026 (ver seção 5 deste arquivo); refazer se o firmware mudar ou para medir o pior caso contínuo.
- Contadores `overruns`, `queue_drops`, `mutex_timeouts` e *stack high-water marks* (linha `S,...`).
- Acurácia ao vivo (tabela do item 6) e comparação com a acurácia do teste offline.
- Valores de `I2S_SAMPLE_SHIFT`, `I2S_CHANNEL_SWAP` e `RMS_GATE_DB` que funcionaram na sua placa.
