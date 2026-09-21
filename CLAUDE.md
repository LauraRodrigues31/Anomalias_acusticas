# CLAUDE.md — Detector de Anomalias Acústicas (Alarme de Fumaça) em ESP32 + FreeRTOS

## 0. Como usar este arquivo

Você (Claude Code) é o engenheiro principal deste projeto. **Este arquivo é a especificação completa.** Leia-o inteiro antes de escrever qualquer código e depois execute as fases da seção 11, em ordem, com commits pequenos.

- **Idioma:** documentação e comentários de código em **português (PT-BR)**. Identificadores, nomes de arquivos e mensagens de commit em **inglês** (Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`).
- **Tempo é curto.** A aluna tem poucas horas. Priorize o núcleo (RTOS + medições + testes) e só depois o polimento.
- **Você não tem acesso ao hardware.** Compile, teste no computador (alvo `native`) e deixe tudo pronto para validação física. Nunca rode `upload` para uma placa sem a aluna pedir.
- **Nunca invente números.** Latências, acurácias e qualquer medição só entram em documentos se vierem de uma execução real. Onde depender do ESP32, escreva `PENDENTE (medir no hardware)`.
- **Não mude decisões fechadas (seção 2) sem justificar por escrito** em `docs/decisions.md` e avisar no resumo final.
- **Consulte os headers e a documentação instalados** (Arduino-ESP32, ESP-IDF, FreeRTOS) em vez de confiar na memória. Não invente APIs.

---

## 1. Contexto

**Disciplina:** Edge Computing / sistemas embarcados (Inteli). Atividade ponderada "Detector de Anomalias Acústicas". Aluna: Laura.

**Prazos:** entrega do repositório em 18/09/2026; checkpoint de demonstração ao vivo + prova escrita (2 questões sobre a implementação) em **21/09/2026 (segunda)**. Hoje é 20/09/2026 (domingo). O histórico de commits deve ser incremental.

**Enunciado (resumo fiel):** implementar um sistema embarcado que detecta anomalias acústicas em tempo real, com **RTOS**, processamento de sinais em edge e sincronização de tarefas concorrentes. Hardware: **ESP32 + microfone I2S INMP441 + LED + buzzer (opcional)**. Arquitetura FreeRTOS com **no mínimo 3 tarefas concorrentes sincronizadas**:

1. **Captura de áudio** (prioridade alta): lê o microfone via I2S continuamente e preenche um buffer circular.
2. **Extração de features** (prioridade média): processa os buffers cheios e calcula características (RMS, Spectral Centroid, MFCCs etc.); escreve numa fila compartilhada.
3. **Detecção de anomalia** (prioridade baixa): lê as features da fila, aplica um modelo pré-treinado e ativa o alerta (LED/buzzer) se a anomalia passar do limiar.

**Requisitos:** capturar áudio continuamente; detectar anomalias com modelo pré-treinado; ≥3 tarefas sincronizadas; **medir e documentar a latência de cada etapa**; alertar por LED/buzzer; **resolver conflitos de concorrência**.

**Entregáveis:** (1) repositório com o código; (2) diagrama de tarefas RTOS (SVG ou imagem) mostrando tarefas, mutexes, semáforos, filas e sincronização; (3) modelo de detecção em arquivo **`.onnx`**; (4) relatório técnico (arquitetura RTOS, análise de latência, resultados, discussão); (5) código de teste que simula anomalias e mede performance.

**Critérios de avaliação (pesos):** Captura e sincronização com RTOS 25% · Checkpoint em sala 20% · Detecção/acurácia 20% · Latência e performance 15% · Implementação de concorrência 15% · Documentação e relatório 5%.

**Consequência prática:** 40% da nota está no firmware RTOS bem feito e documentado; 20% na acurácia; o relatório vale pouco. A demo ao vivo e a prova escrita exigem que a aluna **entenda** o código — por isso a seção 14 (documentação para estudo) é obrigatória.

---

## 2. Decisões fechadas

| Tema | Decisão |
|---|---|
| Som-alvo | **Alarme de fumaça** (detector de fumaça residencial; padrão de 3 bipes + pausa, "T3"). Aplicação prática: **acessibilidade** — alerta visual (LED) para pessoas surdas ou com deficiência auditiva. |
| Negativos que NÃO devem disparar | fala, palmas, chaves, teclado, porta, **toque/despertador de celular, sirene, buzina**, ruído de sala. |
| Aquisição | ESP32 + INMP441 via I2S, **16 kHz**, mono (canal esquerdo, pino L/R do microfone no GND). |
| Janela | **N = 1024 amostras** (64 ms), **passo HOP = 512** (32 ms, 50% de sobreposição). |
| Features | RMS (para gate e log) + Spectral Centroid + razão de energia na banda 2–4 kHz + "peakiness" tonal + frequência do pico. Contrato exato na seção 4. **MFCC não faz parte do núcleo** (só como extra opcional, se tudo estiver pronto). |
| Modelo | Regressão logística (com padronização), exportada para **`.onnx`**. Se não atingir as metas, MLP pequeno (1 camada oculta ≤ 16 unidades). A **inferência roda em C no ESP32** com pesos exportados para header; o `.onnx` é o entregável e é validado contra o C por teste de paridade. |
| Dados | Datasets públicos + sintéticos + augmentation. **A aluna não vai gravar dataset próprio.** |
| Decisão | limiar de probabilidade + regra **N de M** (padrão 3 de 5 janelas) + tempo de espera (cooldown) de 3 s. |
| Alerta | LED obrigatório; buzzer opcional (desligado por padrão) com supressão da detecção durante o toque. |
| Framework | **PlatformIO + Arduino-ESP32** (que usa FreeRTOS). Detalhes na seção 7. |
| Teste | Modo de injeção de áudio pela serial no firmware + alvo `native` no PC. |

---

## 3. Hardware e pinagem (padrões, configuráveis)

Placa assumida: **ESP32 DevKit (esp32dev)**. Os pinos ficam em `firmware/include/board_config.h` (edição manual):

| Sinal | Pino ESP32 | Observação |
|---|---|---|
| INMP441 VDD | 3V3 | **3,3 V**, nunca 5 V |
| INMP441 GND | GND | |
| INMP441 L/R | GND | seleciona canal esquerdo |
| INMP441 SCK (BCLK) | GPIO 26 | `I2S_BCLK_PIN` |
| INMP441 WS (LRCL) | GPIO 25 | `I2S_WS_PIN` |
| INMP441 SD (DOUT) | GPIO 33 | `I2S_DIN_PIN` |
| LED | GPIO 2 (LED da placa) | `LED_PIN`; o LED externo entra com resistor de 220 Ω |
| Buzzer (opcional) | GPIO 27 | `BUZZER_PIN`, `USE_BUZZER 0` por padrão |

O INMP441 entrega amostras de **24 bits alinhadas à esquerda em palavra de 32 bits**. Converta para `int16_t` com um deslocamento configurável (`I2S_SAMPLE_SHIFT`, padrão 16, com saturação) para ficar no mesmo domínio dos WAVs de 16 bits usados no treino. Deve existir também `I2S_CHANNEL_SWAP` (esquerdo/direito) para contornar as peculiaridades conhecidas do driver I2S do ESP32.

---

## 4. Contrato de features (fonte da verdade — Python e C++ devem ser idênticos)

Crie e mantenha **`docs/feature_spec.md`** com este contrato. Qualquer mudança nas features passa primeiro por esse arquivo, depois por Python, C++ e teste de paridade.

**Constantes** (definidas em `ml/config.py` e exportadas para `firmware/include/dsp_config.h` por `ml/gen_headers.py`; não duplique à mão):

- `FS = 16000`, `N = 1024`, `HOP = 512`, `NBINS = 513` (k = 0..512), `DF = FS/N = 15.625 Hz`
- Banda: 2000–4000 Hz → bins **k = 128..256** (inclusive)
- `RMS_GATE_DB = -50.0` (dBFS)
- Decisão: `PROB_THRESHOLD` (calibrado no treino), `VOTE_N = 3`, `VOTE_M = 5`, `COOLDOWN_MS = 3000`, `LED_ON_MS = 2000`

**Cálculo por janela** (entrada: 1024 amostras `int16`; tudo em `float32`):

1. `x[n] = s[n] / 32768.0`
2. **Remoção de DC:** `x[n] -= mean(x)` (o INMP441 tem offset DC).
3. `rms = sqrt(mean(x²))` (após remover DC, antes da janela de Hann); `rms_db = 20·log10(rms + 1e-9)`.
4. Janela de Hann **periódica**: `w[n] = 0.5 − 0.5·cos(2πn/N)`; `xw = x·w`.
5. FFT real de `xw`; `mag[k] = |X[k]|` (sem normalização), k = 0..512. `f_k = k·DF`.
6. Estatísticas espectrais usam **k = 1..512** (sem DC):
   - `centroid_hz = Σ f_k·mag_k / (Σ mag_k + 1e-12)`; **`centroid_norm = centroid_hz / 8000`**
   - `P_k = mag_k²`; `total_power = Σ_{k=1..512} P_k`; `band_power = Σ_{k=128..256} P_k`
   - **`band_ratio = band_power / (total_power + 1e-12)`**
   - **`band_peakiness = max_{k∈[128,256]} P_k / (band_power + 1e-12)`** (alto para tom puro)
   - **`peak_freq_norm = (argmax_{k=1..512} mag_k · DF) / 8000`**

**Vetor de entrada do modelo (ordem fixa):** `[centroid_norm, band_ratio, band_peakiness, peak_freq_norm]`.
**`rms_db` não entra no modelo** (evita dependência do volume absoluto); ele é usado como **gate** (`rms_db < RMS_GATE_DB` ⇒ janela negativa, sem rodar o modelo) e registrado nos logs.

Você pode acrescentar **até 4 features extras invariantes ao volume** (ex.: planicidade espectral na banda, rolloff) se elas melhorarem a validação, mas só via `feature_spec.md` + paridade.

**Teste de paridade:** Python (numpy, float32) vs. implementação C++ nativa nas mesmas janelas de WAVs reais. Tolerâncias iniciais: `rtol = 1e-3`, `atol = 1e-5` (para `centroid_norm`, `atol = 1e-4`). Se falhar, investigue antes de relaxar; se relaxar, documente o motivo numérico.

---

## 5. Modelo e exportação

- Treino em `ml/train.py` com scikit-learn: `StandardScaler` + `LogisticRegression(class_weight="balanced")`; `C` escolhido na validação.
- **Limiar de probabilidade e parâmetros N/M escolhidos somente na validação.** O conjunto de teste é usado **uma única vez**, no final, para o número reportado.
- Exportar `models/detector.onnx` (skl2onnx; saída com probabilidade da classe positiva) e **verificar com onnxruntime** que a saída bate com o scikit-learn.
- Gerar `firmware/include/model_params.h` (`MODEL_N_FEATURES`, `MODEL_MEAN[]`, `MODEL_STD[]`, `MODEL_W[]`, `MODEL_B`, `PROB_THRESHOLD`). Inferência em C++: `z = Σ w_i·(x_i − mean_i)/std_i + b`; `p = 1/(1+expf(−z))`.
- Teste de paridade do modelo: probabilidades do ONNX (Python) ≈ probabilidades da inferência C++ nativa (tolerância 1e-4).
- Se o MLP for necessário, generalize a inferência C++ para camadas densas com ReLU e mantenha a mesma verificação de paridade.

---

## 6. Lógica de decisão (implementada uma vez em C++ portátil, espelhada em Python)

Para cada janela, na ordem:

1. Se `rms_db < RMS_GATE_DB` → `pos = 0`. Senão `p = modelo(features)` e `pos = (p ≥ PROB_THRESHOLD)`.
2. Manter as últimas `VOTE_M` janelas. Se `sum(pos) ≥ VOTE_N` **e** `agora ≥ cooldown_until` **e** não estiver em supressão do buzzer → **ALERTA**; `cooldown_until = agora + COOLDOWN_MS`; LED aceso por `LED_ON_MS`.
3. Se o buzzer estiver habilitado, durante o toque e por 300 ms depois as janelas são ignoradas (evita realimentação).

A classificação **por clipe** (para acurácia) é: "houve pelo menos um ALERTA no clipe".

---

## 7. Arquitetura RTOS (núcleo da nota — capriche e documente cada escolha)

**PlatformIO:** `firmware/platformio.ini` com os ambientes:
- `esp32dev` (produção): `board = esp32dev`, `framework = arduino`, `monitor_speed = 921600`. **Fixe a versão da plataforma** (`espressif32@^6`, que usa Arduino-ESP32 2.0.x / ESP-IDF 4.4, para poder usar `driver/i2s.h`). **Verifique qual core ficou instalado** e use a API I2S correspondente; se preferir o driver novo (`i2s_std.h`), justifique em `docs/decisions.md`.
- `esp32-test`: igual, com `-DAUDIO_SOURCE_SERIAL=1` (áudio injetado pela serial no lugar do I2S).
- `esp32-selftest`: com `-DBOARD_SELFTEST=1` (roteiro de bring-up, seção abaixo).
- `native`: `platform = native`, para testes unitários (Unity) e para o executável `dsp_cli` no PC.

**Código portátil (sem dependências de Arduino/FreeRTOS)** em `firmware/lib/dsp/`: FFT (radix-2 iterativa, `float`, tabelas de twiddle e de Hann pré-calculadas), `features`, `model`, `decision`. **Só a "cola" de hardware/RTOS** (`main`, I2S, tarefas, GPIO) fica em `firmware/src/`. Assim, quase tudo é testável no PC.

### Tarefas (números maiores = prioridade maior no FreeRTOS)

| Tarefa | Prioridade | Núcleo (padrão, medir e documentar) | Função |
|---|---|---|---|
| `T1 audio_capture` | 5 | 0 | `i2s_read` bloqueante (DMA) de blocos de `HOP = 512` amostras → converte para int16 → grava no **buffer circular** → `xSemaphoreGive(blocks_ready)`. Não faz `Serial.print`. |
| `T2 feature_extract` | 3 | 1 | `xSemaphoreTake(blocks_ready)` → monta a janela de 1024 (dois blocos consecutivos) → calcula as features → `xQueueSend(feature_q, &msg, 0)`. |
| `T3 anomaly_detect` | 2 | 1 | `xQueueReceive(feature_q)` → gate + modelo + regra N de M → LED/buzzer → registra tempos. |
| `T4 monitor` | 1 | 1 | A cada 5 s imprime estatísticas sob mutex (contadores, latências, *stack high-water marks*). Também faz o *heartbeat* de status. |

### Objetos de sincronização (cada um precisa de um motivo escrito no diagrama e no relatório)

- **Buffer circular** `RING_BLOCKS = 8` blocos × 512 amostras `int16` (≈ 8 KB), estático. Produtor único (T1) e consumidor único (T2).
- **Semáforo de contagem** `blocks_ready` com contagem máxima `RING_BLOCKS`: T1 dá, T2 pega. **Se o `Give` falhar (contagem no máximo), é um overrun**: T1 incrementa `overruns` e sobrescreve o bloco mais antigo de forma controlada.
- **Fila** `feature_q` (profundidade 8, itens `FeatureMsg` copiados): `window_id`, `t_block_ready_us`, `t_feat_start_us`, `t_feat_done_us`, `rms_db`, 4 features. T2 usa timeout 0; se cheia, descarta e incrementa `queue_drops`.
- **Mutex `log_mutex`**: serializa `Serial` (T3 e T4 escrevem; em modo de teste, os logs por janela também).
- **Mutex `stats_mutex`**: protege a struct `SystemStats` (contadores e acumuladores de latência: escrita por T2/T3, leitura por T4). **Nunca segurar os dois mutexes ao mesmo tempo** (ou definir uma ordem fixa `stats → log`); documente a regra contra deadlock.
- Todas as tomadas de mutex usam **timeout** (ex.: 50 ms); falha incrementa `mutex_timeouts`.
- Sem alocação dinâmica depois da inicialização. Buffers grandes (FFT) estáticos, não na pilha. Nenhuma tarefa faz *busy-wait*: toda espera é bloqueante (evita o watchdog).

### Condições de corrida a documentar (e mostrar no diagrama)

1. T1 escrevendo enquanto T2 lê o buffer (resolvido por semáforo de contagem + índices de produtor/consumidor únicos).
2. Vários escritores na Serial (mutex).
3. Estatísticas escritas por T2/T3 e lidas por T4 (mutex).
4. Realimentação buzzer → microfone (supressão + cooldown).

### Timestamps e latências (`esp_timer_get_time()`, µs)

Defina em `docs/latency_methodology.md` e meça:
- `t_window` (64 ms) e `HOP` (32 ms): latência inerente da janela — **documentada, não medida**.
- `t_sched`: do bloco pronto (T1) até T2 começar.
- `t_feat`: tempo de cálculo das features em T2.
- `t_queue`: espera na fila até T3 receber.
- `t_infer`: gate + modelo + decisão em T3.
- `t_total`: do bloco pronto até o LED/decisão.
- `t_decision`: do início da primeira janela positiva do voto vencedor até o ALERTA.
- Requisito de tempo real: `t_sched + t_feat + t_queue + t_infer` deve ficar bem abaixo de 32 ms (o passo entre janelas).
- Estatísticas: média, p50, p95, máximo, com ≥ 100 amostras.

### Autoteste de bring-up (`BOARD_SELFTEST`)
Piscar o LED; tocar o buzzer por 200 ms (se habilitado); a cada 500 ms imprimir do I2S: valor bruto mín/máx/média, `rms_db` e uma barra de nível ASCII. Serve para a aluna validar fiação, canal L/R, deslocamento de bits e calibrar o `RMS_GATE_DB`.

---

## 8. Protocolo de teste e harness

**Modo `esp32-test` / alvo `native`:** o áudio entra pela serial (ou stdin no `native`) em vez do I2S; T1 alimenta o **mesmo** buffer circular e o resto do pipeline é idêntico.

- Baud: 921600 (a serial leva ~92 KB/s; o áudio int16 a 16 kHz usa 32 KB/s).
- O host envia a linha `START <clip_id> <n_samples>\n`, depois `n_samples` amostras `int16` little-endian (o firmware completa o último bloco com zeros). O host pode enviar em **tempo real** (um bloco de 512 amostras a cada 32 ms) ou `--fast`. O firmware responde `DONE <clip_id>` ao terminar de processar a última janela.
- Linhas de log legíveis por máquina (documente o formato em `docs/serial_protocol.md`), por exemplo:
  `W,<clip_id>,<win>,<t_block_ready_us>,<rms_db>,<cent>,<ratio>,<peakiness>,<pkfreq>,<prob>,<pos>,<t_sched_us>,<t_feat_us>,<t_queue_us>,<t_infer_us>,<t_total_us>`
  `A,<clip_id>,<win>,<t_alert_us>,<t_decision_us>`
  `S,<overruns>,<queue_drops>,<mutex_timeouts>,<hwm_t1>,<hwm_t2>,<hwm_t3>,<hwm_t4>`
- No `native`, os tempos usam `std::chrono` e devem ser rotulados como **"host; não representam o ESP32"**.

**`tests/run_test.py --target native|serial:<porta>`:**
1. Lê o manifesto do conjunto de **teste** (`data/processed/test_manifest.csv`: caminho, rótulo, tipo).
2. Envia cada clipe, coleta `W/A/S`, calcula por clipe: alertou ou não.
3. Reporta acurácia, precisão, recall, FPR, matriz de confusão (também **separada por tipo**: positivo sintético, positivo real, negativo comum, negativo difícil).
4. Reporta latências (média, p50, p95, máx.) por etapa, contadores de overrun/queue_drops e *stack watermarks*.
5. Grava `docs/results/*.csv|json|png` **com carimbo de data e do alvo** (native vs. esp32).
6. **Modo `--simulate-anomalies`:** monta cenas de 10 s (ruído de fundo/negativos + alarme inserido em instante aleatório conhecido, SNR variável) e mede o atraso entre o início do alarme e o ALERTA, em tempo de áudio e em tempo de parede. Esse é o "código de teste que simula anomalias e mede performance" exigido no enunciado.
7. **Modo `--demo-clip <arquivo>`:** roda um áudio real do alarme da demo (fora do treino) e mostra a decisão janela a janela.

`tests/parity_test.py`: paridade das features e do modelo (seções 4 e 5). `firmware/test/` (Unity, alvo `native`): FFT contra valores conhecidos, features em sinais sintéticos (senoide de 3 kHz ⇒ `band_ratio` alto e `peakiness` alta; ruído branco ⇒ baixos), decisão N de M/cooldown, inferência do modelo.

---

## 9. Dados (sem gravação própria)

**Nunca versionar áudio.** `.gitignore` deve cobrir `data/raw/`, `data/processed/`, `.venv/`, `.pio/`, `build/`, `__pycache__/`. Versione só `data/README.md` (fontes, licenças, como reproduzir) e manifestos pequenos.

**Positivos (alarme de fumaça):**
- (a) Hugging Face **`ShantyCam/audiodet-synth-smoke`**: 250 clipes sintéticos, 16 kHz mono, 8 s, CC-BY-4.0 (padrão T3; timbre ≈ 3,1 kHz senoidal ou ≈ 520 Hz quadrado; sem ruído de fundo). Baixe com `huggingface_hub`.
- (b) **Gerador próprio** `ml/gen_smoke_alarm.py`, parametrizado e com semente fixa: piezo 2,8–3,5 kHz, padrões T3/T4 e contínuo, harmônicos, envelope, pequena deriva de frequência, reverberação (convolução com resposta ao impulso sintética de decaimento exponencial, RT60 0,1–0,6 s).
- (c) **Clipes reais**: coloque em `data/raw/smoke_real/` o que existir. Se a pasta estiver vazia, o pipeline **funciona** mas emite aviso e o relatório precisa dizer que não houve positivos reais. **Não faça scraping** do Freesound/YouTube; se precisar de clipes reais, liste em `docs/PEDIDOS_PARA_ALUNA.md` o que buscar manualmente (Freesound: "smoke alarm", "smoke detector"; licenças CC, anotando autor e licença).
- (d) **Áudio da demo** em `data/raw/demo/alarm_demo.wav` (se existir): **fica de fora do treino, validação e teste**; só alimenta `--demo-clip`.

**Negativos:**
- **ESC-50** (`git clone --depth 1 https://github.com/karolpiczak/ESC-50`): 2000 clipes de 5 s, 50 classes. Use todas as classes como negativas. **Negativos difíceis** (marque no manifesto): `clock_alarm`, `siren`, `car_horn`, `church_bells`, `door_wood_knock`, `keyboard_typing`, `mouse_click`, `clapping`, `glass_breaking`, `crying_baby`.
- **Fala**: ESC-50 não tem fala contínua. Use um conjunto pequeno e aberto (ex.: `mini_speech_commands.zip` do TensorFlow, ou um subconjunto do LibriSpeech dev-clean em openslr.org). Verifique a disponibilidade e a licença e registre em `data/README.md`.
- **Ruído de sala**: ruído branco/rosa sintético e classes de ambiente do ESC-50 (chuva, vento, ventilador etc.).
- **FSD50K é grande; não baixe** a menos que sobre tempo e a aluna concorde.

**Pré-processamento:** reamostrar tudo para 16 kHz mono; janelas conforme a seção 4.

**Split:** **por clipe**, nunca por janela (70/15/15, estratificado, semente fixa). Para o ESC-50 pode-se usar os folds oficiais (1–3 treino, 4 validação, 5 teste). Grave o manifesto de cada split.

**Rotulagem de janelas:**
- Janela de clipe positivo: **positiva** só se `rms_db ≥ RMS_GATE_DB` **e** a `band_power` da janela estiver a menos de 20 dB do máximo do clipe (evita rotular o silêncio entre bipes como alarme). Janelas de pausa são **excluídas** do treino.
- Janela de clipe negativo: **negativa** se `rms_db ≥ RMS_GATE_DB`; abaixo do gate, excluída.

**Augmentation (apenas no treino; semente fixa; no nível do clipe, antes das janelas):** ganho aleatório (pico de −40 a −5 dBFS); ruído de fundo somado (SNR 0–30 dB) tirado do pool de negativos; deslocamento no tempo; resposta de alto-falante/microfone simulada (passa-banda ~300 Hz–7 kHz e leve inclinação de EQ); reverberação sintética; **mistura de alarme sobre fala/ruído** (imita a demo); clipping leve ocasional.

---

## 10. Estrutura do repositório

```
CLAUDE.md
README.md
requirements.txt
.gitignore
docs/
  enunciado.pdf                (se a aluna copiar o PDF do enunciado)
  feature_spec.md  decisions.md  latency_methodology.md  serial_protocol.md
  diagrama_tarefas.svg
  relatorio_tecnico.md  STUDY.md  HARDWARE_CHECKLIST.md  PEDIDOS_PARA_ALUNA.md
  results/
data/
  README.md
  raw/  processed/             (ignorados pelo git)
ml/
  config.py  gen_headers.py  features.py  decision.py
  gen_smoke_alarm.py  build_dataset.py  augment.py
  train.py  evaluate.py  export_onnx.py
models/
  detector.onnx
firmware/
  platformio.ini
  include/  board_config.h  dsp_config.h (gerado)  model_params.h (gerado)
  lib/dsp/  fft.*  features.*  model.*  decision.*
  src/      main.cpp  audio_capture.*  tasks.*  alert.*  stats.*  selftest.*
  test/     (Unity, alvo native)
  tools/    dsp_cli.cpp        (executável nativo: stdin → linhas W/A/S)
tests/
  run_test.py  parity_test.py
```

---

## 11. Fases (execute em ordem; commit ao fim de cada uma; rode os testes indicados)

**Fase 0 — Bootstrap.** Verifique `git`, `python3`, `pio` (instale com `pip install platformio` se faltar), `g++`. Crie a estrutura, `.gitignore`, `requirements.txt` (numpy, scipy, scikit-learn, skl2onnx, onnx, onnxruntime, soundfile, pandas, matplotlib, pyserial, huggingface_hub), `ml/config.py`, `docs/feature_spec.md`, `docs/decisions.md`. Commit: `chore: initial structure`.

**Fase 1 — Biblioteca DSP portátil + testes nativos.** FFT, features, modelo (com parâmetros provisórios), decisão N de M + cooldown; `ml/features.py` e `ml/decision.py` como referência; `tools/dsp_cli.cpp`; testes Unity; `tests/parity_test.py` (features). Teste: `pio test -e native` e paridade passam. Commit: `feat: portable dsp library and parity tests`.

**Fase 2 — Firmware RTOS (prioridade máxima da nota).** `board_config.h`, captura I2S com conversão e `I2S_CHANNEL_SWAP`/`I2S_SAMPLE_SHIFT`, buffer circular, semáforo de contagem com detecção de overrun, fila, 2 mutexes, T1–T4, LED/buzzer com supressão, cronometragem por etapa, `SystemStats`, autoteste, fonte de áudio por serial. Enquanto o modelo real não existe, use um detector provisório baseado em `band_ratio` e `band_peakiness` (marcado como provisório). **Teste:** `pio run -e esp32dev`, `-e esp32-test` e `-e esp32-selftest` compilam sem warnings relevantes. Ao terminar, **escreva a primeira versão de `docs/HARDWARE_CHECKLIST.md`** (fiação, autoteste, o que já dá para validar na placa; ver seção 13). Commits: `feat: i2s audio capture`, `feat: rtos task architecture`, `feat: latency instrumentation`, `feat: board selftest`.

**Fase 3 — Dados.** Gerador sintético, download do dataset do Hugging Face e do ESC-50, fala, `build_dataset.py` (reamostragem, splits por clipe, rotulagem de janelas, augmentation, manifestos), `data/README.md` com fontes e licenças. Se algo não puder ser baixado, siga com o que houver e registre em `docs/PEDIDOS_PARA_ALUNA.md`. Commit: `feat: dataset pipeline`.

**Fase 4 — Treino, avaliação, ONNX e integração.** `train.py`, `evaluate.py` (janela e clipe; validação; teste uma vez), `export_onnx.py`, `gen_headers.py`; substitua o detector provisório pelo modelo real; testes de paridade do modelo; gráficos (matriz de confusão, curva precisão-recall) em `docs/results/`. **Metas indicativas no teste, por clipe:** recall do alarme ≥ 90% e FPR ≤ 5%. Se não atingir, itere (features extras, augmentation, MLP) **usando a validação**, nunca o teste; se ainda assim não atingir, reporte o número real com honestidade. Commit: `feat: model training and onnx export`, `feat: on-device inference`.

**Fase 5 — Harness de teste.** `tests/run_test.py` com alvos `native` e `serial`, `--simulate-anomalies`, `--demo-clip`; rode no `native` e salve os resultados (rotulados como host). O alvo `serial` deve estar implementado e revisado, mas é marcado como não validado até a aluna testar na placa. Commit: `feat: latency measurement and test harness`.

**Fase 6 — Diagrama e metodologia.** `docs/diagrama_tarefas.svg` escrito à mão (SVG): tarefas com prioridades e núcleos, buffer circular, semáforo de contagem, fila, os dois mutexes, LED/buzzer, Serial, e as setas de sincronização, com legenda. Renderize para PNG e confira visualmente se possível. `docs/latency_methodology.md`. Commit: `docs: task diagram and latency methodology`.

**Fase 7 — Documentação.** `README.md` (como compilar, gravar, testar, reproduzir dados e treino), `docs/relatorio_tecnico.md` (aplicação prática e justificativa; arquitetura RTOS e cada escolha de sincronização; análise de latência com tabelas **preenchidas somente com medições reais** e `PENDENTE` onde depender do ESP32; resultados de acurácia; discussão: diferença entre dado sintético/limpo e microfone real, limitações, riscos, trabalhos futuros; referências), `docs/STUDY.md` (seção 14), `docs/HARDWARE_CHECKLIST.md` final. Commit: `docs: report, study guide and hardware checklist`.

**Fase 8 — Revisão final.** Rode tudo (`pio test -e native`, `pio run` nos três ambientes, paridade, `run_test.py --target native`). Confira a lista da seção 12. Corrija o que falhar. Commit final e resumo (seção 15).

---

## 12. Critérios de aceite

- [ ] `pio run -e esp32dev`, `-e esp32-test`, `-e esp32-selftest` compilam; `pio test -e native` passa.
- [ ] Paridade Python × C++ das features e do modelo dentro das tolerâncias.
- [ ] `models/detector.onnx` existe e foi verificado com onnxruntime.
- [ ] Métricas de validação e de teste reportadas com honestidade, separadas por tipo (sintético/real, comum/difícil).
- [ ] Firmware com ≥ 3 tarefas (T1–T3 + monitor), buffer circular, semáforo de contagem, fila e 2 mutexes, com contadores de overrun/queue_drops/mutex_timeouts e *stack watermarks*.
- [ ] Nenhum `Serial.print` em T1; nenhuma alocação dinâmica após o init; nenhum mutex sem timeout.
- [ ] `docs/diagrama_tarefas.svg` fiel ao código.
- [ ] `tests/run_test.py` funciona no `native` e gera resultados em `docs/results/`.
- [ ] `README.md`, `relatorio_tecnico.md`, `STUDY.md`, `HARDWARE_CHECKLIST.md`, `data/README.md`, `feature_spec.md`, `decisions.md` presentes.
- [ ] Nenhum áudio versionado; licenças e fontes registradas.
- [ ] Histórico de commits incremental, em Conventional Commits.

---

## 13. `docs/HARDWARE_CHECKLIST.md` (a aluna vai montar o hardware depois; deixe pronto)

Deve conter, em português e em ordem de execução:
1. **Tabela de fiação** (a da seção 3), com aviso de 3,3 V.
2. Como compilar e gravar o `esp32-selftest` e o que esperar na serial.
3. Como interpretar o autoteste: valores brutos mín/máx/média, offset DC, canal L/R (`I2S_CHANNEL_SWAP`), deslocamento de bits (`I2S_SAMPLE_SHIFT`), sinais de fiação errada (leitura travada em zero, ruído enorme, canal trocado).
4. Como **calibrar `RMS_GATE_DB`** e o `PROB_THRESHOLD` na sala real, tocando o alarme do celular a 30–50 cm.
5. Como gravar o `esp32dev` e rodar o `esp32-test` com `tests/run_test.py --target serial:<porta>` para preencher as tabelas de latência do relatório.
6. Roteiro de ensaio da demo (10 repetições, anotando acertos e erros) e plano B (log da serial salvo, vídeo, cabo reserva).
7. O que preencher no relatório depois das medições reais.

---

## 14. `docs/STUDY.md` (a aluna precisa explicar o código na prova escrita e na demo)

A aluna vai estudar por este arquivo. Escreva em português claro, do concreto para o abstrato, com analogias curtas. Conteúdo:
1. **Visão geral em 5 linhas** e um fluxo em texto ASCII.
2. **Passeio pelos arquivos**: para cada arquivo/função relevante, *o que faz*, *por que existe* e *como se conecta* às tarefas (com nomes reais de arquivos e funções).
3. **Cada objeto de sincronização**: o que protege, que problema resolve, o que quebraria sem ele.
4. **Por que as prioridades são 5/3/2/1** e o que aconteceria se fossem invertidas.
5. **Pipeline de sinal**: janela, Hann, FFT, cada feature em linguagem simples.
6. **Como o modelo nasceu e chegou ao ESP32** (treino → `.onnx` → header → C++), e por que a paridade importa.
7. **Como a latência foi medida** e o que cada número significa.
8. **Roteiro da demo** e "o que dizer".
9. **12 perguntas de prova com respostas fundamentadas no código real** (com arquivo e função citados):
   1) por que a captura tem prioridade mais alta; 2) papel do semáforo entre T1 e T2 (e por que não polling); 3) por que fila entre T2 e T3 e o que acontece quando enche; 4) por que mutex e não semáforo binário (herança de prioridade); 5) onde há condição de corrida e como foi evitada; 6) o que é overrun e como é detectado; 7) o que é o Spectral Centroid e por que separa o alarme da voz; 8) por que janela de 1024 a 16 kHz e qual a latência inerente; 9) como o modelo roda no ESP32 se o entregável é `.onnx`; 10) por que dividir treino/teste por clipe; 11) por que a acurácia ao vivo pode ser menor que a do teste; 12) como se mediu a latência de cada etapa.
10. **Glossário** (RTOS, ISR/DMA, mutex, semáforo, fila, overrun, quantização de 24→16 bits, FFT, Hann, centroid, gate, N de M, cooldown).

As respostas devem refletir o código que existe de fato; se você mudar o código depois, atualize o estudo.

---

## 15. Regras de conduta

**Faça:** commits pequenos e frequentes; rode testes ao fim de cada fase; comente o *porquê* (não só o *quê*) no código, principalmente nas partes de RTOS; registre decisões em `docs/decisions.md`; se houver `origin` configurado, faça `git push` ao fim de cada fase.

**Não faça:**
- não invente resultados de medição, acurácia ou latência;
- não ajuste limiares ou hiperparâmetros olhando o conjunto de teste;
- não versione áudio, datasets, `.venv` ou `.pio`;
- não faça scraping de sites que exigem login/termos (Freesound, YouTube); peça à aluna;
- não use `git push --force` nem altere a configuração global do git;
- não grave firmware em placa sem a aluna pedir;
- não relaxe uma tolerância de paridade para "fazer passar" sem entender a causa;
- não mude decisões da seção 2 sem justificar e avisar.

**Se travar** em algo que só a aluna resolve (dado indisponível, escolha de placa), registre em `docs/PEDIDOS_PARA_ALUNA.md`, siga com o que for possível e sinalize no resumo final.

---

## 16. Resumo final que você deve entregar à aluna

Ao terminar, responda com: (1) o que foi feito por fase; (2) resultados reais de acurácia (validação e teste, por tipo) e o que ficou abaixo da meta; (3) o que **depende do hardware** e está no `HARDWARE_CHECKLIST.md`; (4) decisões que você tomou ou mudou; (5) pedidos pendentes para a aluna; (6) os 3 maiores riscos que você enxerga para a demo; (7) o comando exato para compilar, gravar e testar.
