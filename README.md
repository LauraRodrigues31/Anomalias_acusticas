# Detector de anomalias acústicas (alarme de fumaça) — ESP32 + FreeRTOS

Atividade ponderada de Edge Computing (Inteli). O ESP32 escuta um microfone I2S (INMP441), extrai features espectrais em tempo real e acende um **LED** quando reconhece o **alarme de um detector de fumaça** (padrão de 3 bipes + pausa). Aplicação prática: **acessibilidade**, alerta visual para pessoas surdas ou com deficiência auditiva.

Arquitetura: 4 tarefas FreeRTOS (captura → features → detecção → monitor) sincronizadas por buffer circular, semáforo de contagem, fila e 2 mutexes. Diagrama: [`docs/diagrama_tarefas.svg`](docs/diagrama_tarefas.svg). Detalhes, números e limitações: [`docs/relatorio_tecnico.md`](docs/relatorio_tecnico.md). Para estudar o código: [`docs/STUDY.md`](docs/STUDY.md) e [`docs/GUIA_DO_REPO.md`](docs/GUIA_DO_REPO.md).

> **Estado:** latência e robustez do ESP32 foram **medidas** (relatório, seção 6.2) e há só uma **amostra pequena** de resultados ao vivo (seção 7). O alvo serial do `tests/run_test.py` e a acurácia ao vivo sistemática **não foram validados**.

## Hardware e ligação

**Materiais:** ESP32 DevKit (`esp32dev`), microfone I2S **INMP441**, 1 LED + resistor de **220 Ω a 1 kΩ**, jumpers e protoboard. Buzzer ativo: opcional e **desligado** por padrão (`USE_BUZZER 0`).

> ⚠️ O INMP441 é alimentado com **3,3 V** (nunca 5 V). Fios curtos (< 15 cm) para o I2S.

| Sinal | Pino ESP32 | Constante (`firmware/include/board_config.h`) |
|---|---|---|
| INMP441 SCK (BCLK) | GPIO 26 | `I2S_BCLK_PIN` |
| INMP441 WS (LRCL) | GPIO 25 | `I2S_WS_PIN` |
| INMP441 SD (DOUT) | GPIO 33 | `I2S_DIN_PIN` |
| INMP441 L/R | GND | seleciona o canal (ver `I2S_CHANNEL_SWAP`) |
| INMP441 VDD | 3V3 | — |
| INMP441 GND | GND | — |
| LED | GPIO 13 → resistor → LED → GND | `LED_PIN` |
| Buzzer ativo (opcional, desligado) | GPIO 27 | `BUZZER_PIN` (habilite com `-DUSE_BUZZER=1`) |

No bring-up foi preciso **inverter `I2S_CHANNEL_SWAP` (0 → 1)**, e a gravação foi feita a **115200 baud** (`upload_speed` em `firmware/platformio.ini`); o monitor serial usa 921600. Fiação, autoteste e diagnóstico de sintomas: [`docs/HARDWARE_CHECKLIST.md`](docs/HARDWARE_CHECKLIST.md).

## Como rodar a demo

Ambiente pronto (seção "Preparar o ambiente" abaixo) e placa ligada conforme a tabela.

1. Grave o firmware de produção: `cd firmware && pio run -e esp32dev -t upload` (grava a 115200 baud). Se a fiação ainda não foi conferida, rode antes o autoteste (`-e esp32-selftest`, ver o checklist).
2. Abra o monitor a **921600**: `pio device monitor -b 921600`. Na partida aparecem `# Detector de anomalias acusticas ...` e `# limiar ao vivo (override calibrado) = 0.990; treino = 0.900`.
3. Toque o **alarme de fumaça** perto do microfone (distância pretendida: 30–50 cm).
4. **Esperado:** o **LED acende** (2 s) e a serial mostra uma linha `A,0,<janela>,<t_alerta_us>,<t_decisao_us>` (após ≈ 160 ms ou mais de decisão pelo voto 6 de 8). A cada 5 s saem as estatísticas (`# ...`, `P,...`, `S,...`).
5. Ajuste **sem regravar** (só em RAM; um reset volta ao valor inicial), digitando no monitor uma linha + Enter: `STATS` (mostra os parâmetros na linha `P`), `THR <0-1>`, `GATE <dBFS>`, `VOTE <n> <m>`, `MON 1|0` (uma linha `M` por janela). Protocolo: [`docs/serial_protocol.md`](docs/serial_protocol.md).
6. O **limiar inicial ao vivo é 0,99** (o do treino é 0,9), calibrado ao vivo no ESP32 e **sem validação independente**: `docs/decisions.md`, **D11**. Para recalibrar (feche o monitor antes, a porta é exclusiva): `python tests/calibrate.py --port /dev/ttyUSB0 --sessao`.

Plano B se o microfone falhar: grave o `esp32-test` e envie um WAV pelo USB com `python tests/run_test.py --target serial:/dev/ttyUSB0 --demo-clip <arquivo.wav>` (não validado na placa).

## Resultados em resumo

Todos os números abaixo estão no relatório; aqui só o essencial.

**Acurácia offline por clipe** (conjunto de teste, usado uma única vez; limiar 0,9, voto 6 de 8; relatório, seção 5.2): **recall 93,6% (73/78)**, **FPR 2,6% (12/466)**, acurácia 96,9%. Sintético: recall 93,3% (70/75). Negativo comum: FPR 1,6% (6/386). **Negativos difíceis** (sirene, buzina, despertador etc.): **FPR 7,5% (6/80)**, acima da meta de 5%. Alarme real: 3/3, amostra minúscula.

**Latência medida no ESP32** (`esp32dev`, 21/09/2026, n = 53.570 janelas ≈ 28,6 min, silêncio com alarmes ocasionais, **não** o pior caso; relatório, seção 6.2):

| Etapa | média (µs) | p50 | p95 | máx |
|---|---|---|---|---|
| `t_feat` | 1379 | 1377 | 1377 | 1603 |
| `t_total` (por janela) | 1452 | 1448 | 1450 | 1818 |
| `t_decision` (n = 25 alertas) | 178126 | 161558 | 225471 | 225471 |

`t_total` é o processamento por janela e **não** inclui a janela (64 ms) nem o passo (32 ms); compare com o orçamento de 32 ms. Contadores: `overruns` = 0, `queue_drops` = 0, `torn_reads` = 0, `mutex_timeouts` = 0. Stack livre mínima (bytes): T1 3396, T2 3404, T3 2500, T4 4228.

**Limitações** (relatório, seções 7 e 8): poucos alarmes reais no teste (3); ao vivo há só uma **amostra pequena**, sem intervalo de confiança, com **folga estreita** (o alarme chegou a prob 0,998 e o limiar é 0,99); a calibração ao vivo **não tem validação independente**; heap/CPU não foram medidos; o seqlock do buffer circular não tem teste de estresse.

## Mapa dos entregáveis

| Entregável | Onde |
|---|---|
| Repositório com o código | `firmware/` (RTOS, DSP portátil, testes Unity), `ml/` (dados, treino, exportação), `tests/` |
| Diagrama de tarefas RTOS | [`docs/diagrama_tarefas.svg`](docs/diagrama_tarefas.svg) |
| Modelo em `.onnx` | [`models/detector.onnx`](models/detector.onnx) (pesos em `models/model_params.json`) |
| Relatório técnico | [`docs/relatorio_tecnico.md`](docs/relatorio_tecnico.md) |
| Código de teste que simula anomalias e mede performance | [`tests/run_test.py`](tests/run_test.py) (`--simulate-anomalies`), [`tests/parity_test.py`](tests/parity_test.py), `firmware/test/` |

## Estrutura

```
firmware/  lib/dsp (FFT, features, modelo, decisão, comandos: C++ portátil) · src (I2S, tarefas RTOS, alerta) · test (Unity) · tools/dsp_cli.cpp
ml/        config, features, dataset, treino, avaliação, exportação ONNX, geração de headers
models/    detector.onnx (entregável) · model_params.json · detector.joblib
tests/     run_test.py (harness) · parity_test.py (Python × C++) · calibrate.py (calibração ao vivo) · fake_esp32.py (dispositivo simulado)
docs/      diagrama, relatório, estudo, checklist, contrato de features, protocolo serial, resultados
data/      README.md (fontes e licenças); áudio NÃO é versionado
```

## Preparar o ambiente

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # inclui PlatformIO
```

## Compilar, testar e gravar o firmware

```bash
cd firmware
pio test -e native                        # testes Unity (FFT, features, modelo, decisão, comandos)
pio run -e native-cli                     # executável dsp_cli (usado pelos testes no PC)
pio run -e esp32dev                       # produção (I2S)
pio run -e esp32-test                     # áudio injetado pela serial (para tests/run_test.py)
pio run -e esp32-selftest                 # bring-up: fiação, canal L/R, deslocamento de bits
pio run -e esp32dev -t upload             # grava a produção (só com a placa conectada)
pio device monitor -b 921600
```

Pinos e constantes de placa: `firmware/include/board_config.h`. Constantes de DSP/decisão e pesos do modelo são **gerados** (`dsp_config.h`, `model_params.h`) por `python -m ml.gen_headers`; não edite à mão. O limiar ao vivo (0,99) é um override de configuração (`LIVE_PROB_THRESHOLD`, D11) e **não** altera o `model_params.h`.

## Testar o pipeline no PC

```bash
python -m tests.parity_test                                                       # features e modelo: Python × C++ (+ ONNX)
python tests/run_test.py --target native --split val                              # acurácia por clipe/tipo + latência (tempos do HOST)
python tests/run_test.py --target native --simulate-anomalies --split val         # 40 cenas de 10 s: 40/40 (relatório, seção 5)
python tests/run_test.py --target native --simulate-anomalies                     # padrão: --split test (39/40, ver relatório)
python tests/run_test.py --target native --demo-clip <arquivo.wav>                # decisão janela a janela de um WAV
python tests/run_test.py --target serial:/dev/ttyUSB0 --demo-clip <arquivo.wav>   # plano B: manda o áudio pelo USB (firmware esp32-test)
python tests/run_test.py --target serial:/dev/ttyUSB0 --split val --max-per-type 10   # ESP32 (não validado)
```

`--split` aceita `val` ou `test` (padrão `test`); `--target serial:<porta>` aceita `--fast`. Resultados em `docs/results/` (carimbados com o alvo). Tempos do `native` **não representam o ESP32**. O arquivo `data/raw/demo/alarm_demo.wav` **não existe** no repositório: use qualquer WAV (por exemplo um clipe de `data/raw/smoke_real/`, depois de baixar os dados).

## Calibração ao vivo

Firmware `esp32dev` gravado e monitor serial **fechado** (a porta é exclusiva). Comandos de serial e detalhes: [`docs/HARDWARE_CHECKLIST.md`](docs/HARDWARE_CHECKLIST.md), seção 4.

```bash
python tests/calibrate.py --port /dev/ttyUSB0 --sessao [--segundos 20] [--apply]   # sessão guiada; grava docs/results/calibracao_<data>.csv (não versionado)
python tests/calibrate.py --analisar docs/results/calibracao_<data>.csv            # refaz a análise sem a placa
python tests/calibrate.py --port /dev/ttyUSB0 --label silencio|fala|alarme|despertador|palma|palma_mesa|sirene|toque|alarme_fumaca --seconds 10   # uma coleta avulsa
python tests/calibrate.py --suggest [--port /dev/ttyUSB0 --apply]                  # sugestão a partir das coletas avulsas
```

Sem placa dá para ensaiar com `python tests/fake_esp32.py --live <wav> --speed 8` (imprime um pty; use-o como `--port`). Se o `pio` não estiver disponível, `DSP_CLI=/caminho/dsp_cli` aponta os testes para um `dsp_cli` compilado à mão.

## Reproduzir dados e treino

```bash
# 1) fontes (ver data/README.md): ESC-50, mini_speech_commands, Hugging Face, Freesound (API oficial)
cp .env.example .env   # preencha FREESOUND_API_KEY (o .env não é versionado)
python -m ml.fetch_freesound [--max 40] && python -m ml.curate_real
# 2) dataset, treino, exportação e headers
python -m ml.build_dataset
python -m ml.train                        # escolhe C, limiar e N de M na VALIDAÇÃO
python -m ml.export_onnx                  # models/detector.onnx + verificação com onnxruntime
python -m ml.gen_headers                  # firmware/include/{dsp_config,model_params}.h
python -m ml.evaluate --split val
python -m ml.evaluate --split test        # UMA vez (trava em models/.test_used; --allow-test-rerun ignora a trava)
```

## Documentação

`docs/feature_spec.md` (contrato das features) · `docs/decisions.md` · `docs/latency_methodology.md` · `docs/serial_protocol.md` · `docs/HARDWARE_CHECKLIST.md`.

## Licenças dos dados

Ver `data/README.md` e a seção 9 do relatório. Clipes do Freesound são CC0/CC-BY (autores em `data/raw/smoke_real/SOURCES.csv`, que não é versionado, e na seção 9.1 do relatório).
