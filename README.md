# Detector de anomalias acústicas (alarme de fumaça) — ESP32 + FreeRTOS

Atividade ponderada de Edge Computing (Inteli). O ESP32 escuta um microfone I2S (INMP441), extrai features espectrais em tempo real e acende um **LED** quando reconhece o **alarme de um detector de fumaça** (padrão de 3 bipes + pausa). Aplicação prática: **acessibilidade**, alerta visual para pessoas surdas ou com deficiência auditiva.

Arquitetura: 4 tarefas FreeRTOS (captura → features → detecção → monitor) sincronizadas por buffer circular, semáforo de contagem, fila e 2 mutexes. Diagrama: [`docs/diagrama_tarefas.svg`](docs/diagrama_tarefas.svg). Relatório: [`docs/relatorio_tecnico.md`](docs/relatorio_tecnico.md). Para estudar o código: [`docs/STUDY.md`](docs/STUDY.md).

> **Estado:** firmware compila e o pipeline foi testado no PC. **Nada foi medido/validado no hardware ainda** (latências do ESP32 = `PENDENTE`). Ver [`docs/HARDWARE_CHECKLIST.md`](docs/HARDWARE_CHECKLIST.md).

## Estrutura

```
firmware/  lib/dsp (FFT, features, modelo, decisão: C++ portátil) · src (I2S, tarefas RTOS, alerta) · test (Unity) · tools/dsp_cli.cpp
ml/        config, features, dataset, treino, avaliação, exportação ONNX, geração de headers
models/    detector.onnx (entregável) · model_params.json · detector.joblib
tests/     run_test.py (harness) · parity_test.py (Python × C++)
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
pio test -e native                        # testes Unity (FFT, features, modelo, decisão)
pio run -e native-cli                     # executável dsp_cli (usado pelos testes no PC)
pio run -e esp32dev                       # produção (I2S)
pio run -e esp32-test                     # áudio injetado pela serial (para tests/run_test.py)
pio run -e esp32-selftest                 # bring-up: fiação, canal L/R, deslocamento de bits
pio run -e esp32-selftest -t upload       # grava (só com a placa conectada e a fiação conferida)
pio device monitor -b 921600
```

Pinos e constantes de placa: `firmware/include/board_config.h`. Constantes de DSP/decisão e pesos do modelo são **gerados** (`dsp_config.h`, `model_params.h`) por `python -m ml.gen_headers`; não edite à mão.

## Testar o pipeline no PC

```bash
python -m tests.parity_test                                   # features e modelo: Python × C++ (+ ONNX)
python tests/run_test.py --target native --split val          # acurácia por clipe/tipo + latência (tempos do HOST)
python tests/run_test.py --target native --simulate-anomalies # cenas de 10 s com alarme em instante conhecido
python tests/run_test.py --target native --demo-clip data/raw/demo/alarm_demo.wav
python tests/run_test.py --target serial:/dev/ttyUSB0 --demo-clip data/raw/demo/alarm_demo.wav   # plano B: manda o áudio pelo USB ao ESP32 (firmware esp32-test)
python tests/run_test.py --target serial:/dev/ttyUSB0 --split val --max-per-type 10   # ESP32 (não validado)
```

Resultados em `docs/results/` (carimbados com o alvo). Tempos do `native` **não representam o ESP32**.

**Calibração ao vivo** (firmware `esp32dev` gravado; ver `docs/HARDWARE_CHECKLIST.md`, seção 4): comandos de serial `GATE`, `THR`, `VOTE`, `MON`, `STATS` (só em RAM) e `python tests/calibrate.py --port <porta> --label silencio|fala|alarme|despertador|palma` / `--suggest`. Sem placa dá para ensaiar com `python tests/fake_esp32.py --live <wav> --speed 8`. Se o `pio` não estiver disponível, `DSP_CLI=/caminho/dsp_cli` aponta os testes para um `dsp_cli` compilado à mão.

## Reproduzir dados e treino

```bash
# 1) fontes (ver data/README.md): ESC-50, mini_speech_commands, Hugging Face, Freesound (API oficial)
cp .env.example .env   # preencha FREESOUND_API_KEY (o .env não é versionado)
python -m ml.fetch_freesound && python -m ml.curate_real
# 2) dataset, treino, exportação e headers
python -m ml.build_dataset
python -m ml.train                        # escolhe C, limiar e N de M na VALIDAÇÃO
python -m ml.export_onnx                  # models/detector.onnx + verificação com onnxruntime
python -m ml.gen_headers                  # firmware/include/{dsp_config,model_params}.h
python -m ml.evaluate --split val
python -m ml.evaluate --split test        # UMA vez (trava em models/.test_used)
```

## Documentação

`docs/feature_spec.md` (contrato das features) · `docs/decisions.md` · `docs/latency_methodology.md` · `docs/serial_protocol.md` · `docs/PEDIDOS_PARA_ALUNA.md`.

## Licenças dos dados

Ver `data/README.md`. Clipes do Freesound são CC0/CC-BY (autores em `data/raw/smoke_real/SOURCES.csv`, que não é versionado).
