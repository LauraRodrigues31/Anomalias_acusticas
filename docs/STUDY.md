# Guia de estudo (Laura) — para a demo e a prova escrita

Leia na ordem. Tudo aqui descreve o **código que existe** neste repositório. Se você mudar o código, atualize este arquivo.

## 1. Visão geral em 5 linhas

1. O microfone INMP441 manda amostras de áudio para o ESP32 pelo barramento I2S (16 000 por segundo).
2. A tarefa **T1** guarda o áudio em blocos de 512 amostras num **buffer circular** e avisa a **T2** com um semáforo.
3. A **T2** junta dois blocos (1024 amostras = 64 ms), calcula 4 números que resumem o "formato" do som (features) e os manda numa **fila**.
4. A **T3** vê se o som parece alarme de fumaça (modelo) e se isso se repete em 6 das últimas 8 janelas; se sim, acende o **LED**.
5. A **T4** imprime estatísticas a cada 5 s e, no firmware de produção, aceita comandos pela serial (`GATE`, `THR`, `VOTE`, `MON`, `STATS`) para ajustar o gate, o limiar e o voto **sem regravar** (só em RAM). Dois **mutexes** evitam que as tarefas se atropelem na serial e nas estatísticas.

```
 INMP441 --I2S/DMA--> [T1 captura P5,core0] --ring_write--> [g_ring 8x512] --Give--> (blocks_ready)
                                                                                       |Take
 LED <-- [T3 detecção P2] <--feature_q (8 msgs)-- [T2 features P3,core1] <-------------+
            |  \--stats_mutex--> SystemStats <--stats_mutex-- [T4 monitor P1] (lê a cada 100 ms)
            \--log_mutex--> Serial <--log_mutex-- T4
```

## 2. Passeio pelos arquivos

### Firmware — "cola" de hardware/RTOS (`firmware/src/`)

| Arquivo / função | O que faz | Por que existe | Conexão |
|---|---|---|---|
| `main.cpp` `setup()` | abre a Serial (921600), chama `dsp_init()` (tabelas de FFT/Hann), `rtos_start()` e apaga a tarefa `loop` do Arduino (`vTaskDelete(NULL)`) | ponto de entrada | cria tudo |
| `tasks.cpp` `rtos_start()` | cria semáforo, fila, 2 mutexes e as 4 tarefas | **toda** alocação dinâmica acontece aqui, uma vez | ver seção 3 |
| `tasks.cpp` `t1_audio_capture` | lê um bloco (`audio_read_block`), carimba `t_block_ready`, `ring_write`, `xSemaphoreGive(blocks_ready)`; se o Give falha, `g_overruns++` | captura contínua sem perder amostras | alimenta T2 |
| `tasks.cpp` `t2_feature_extract` | `xSemaphoreTake`, `ring_read`, monta a janela (metade antiga + bloco novo), `features_compute`, `xQueueSend(...,0)` | separa "receber áudio" de "calcular" | alimenta T3 |
| `tasks.cpp` `t3_anomaly_detect` | `xQueueReceive` (timeout 20 ms), gate de RMS, `model_predict`, `decision_update`, `alert_trigger`, calcula as latências | decisão e alerta | usa `lib/dsp`, `alert.cpp`, `stats` |
| `tasks.cpp` `t4_monitor` | a cada 100 ms: `poll_serial_commands` (comandos `GATE/THR/VOTE/MON/STATS`, interpretados por `lib/dsp/runtime_params.cpp`) e linhas `M` por janela; a cada 5 s copia `g_stats` sob `stats_mutex`, solta, imprime | observabilidade e ajuste ao vivo | lê estatísticas; escreve `g_params` |
| `tasks.cpp` `take()` | pega um mutex com timeout de 50 ms; se falhar, `g_mutex_timeouts++` | nenhum mutex sem timeout | usado por T2/T3/T4 |
| `tasks.cpp` `serial_log()` | `vsnprintf` num buffer estático **dentro** do `log_mutex` e `Serial.write` | evitar linhas misturadas | T3/T4 |
| `audio_capture.cpp` `audio_init` / `audio_read_block` | configura o I2S (driver legado `driver/i2s.h`) e lê 512 palavras de 32 bits, convertendo com `audio_convert_sample` (`>> I2S_SAMPLE_SHIFT` + saturação). No `esp32-test` a fonte é a serial | traduz o INMP441 (24 bits alinhados à esquerda) para `int16` do treino | usado só por T1 |
| `ring.cpp` `ring_write` / `ring_read` | buffer circular com número de sequência por slot | resolver a corrida T1×T2 no overrun | T1 escreve, T2 lê |
| `alert.cpp` | LED (GPIO 2), buzzer opcional, `alert_suppressed()` | alerta + evitar realimentação | T3 |
| `stats.cpp` `lat_add`, `lat_percentile` | acumula latências e calcula p50/p95 | medir | T3 escreve, T4 lê |
| `selftest.cpp` | bring-up: LED, buzzer, mín/máx/média/RMS do I2S com barra ASCII | validar fiação | só no `esp32-selftest` |
| `include/board_config.h` | pinos, prioridades, núcleos, pilhas, `I2S_SAMPLE_SHIFT`, `I2S_CHANNEL_SWAP` | configuração num lugar só | tudo |

### Firmware — biblioteca portátil (`firmware/lib/dsp/`, roda no PC também)

| Arquivo / função | O que faz |
|---|---|
| `fft.cpp` `dsp_init`, `fft_real_mag` | FFT radix-2 iterativa de 1024 pontos em `float`; tabelas de seno/cosseno, Hann e bit-reversal pré-calculadas em `dsp_init` |
| `audio_features.cpp` `features_compute` | DC, RMS, Hann, FFT, centroide, `band_ratio`, `band_peakiness`, `peak_freq_norm` |
| `model.cpp` `model_predict` | regressão logística com os pesos de `model_params.h` |
| `decision.cpp` `decision_update` | regra N de M (N e M são argumentos, podem mudar por `VOTE`) + cooldown + supressão (ignora a janela) |
| `runtime_params.cpp` `cmd_execute` | valida e aplica os comandos de serial em `RuntimeParams` (testado no PC) |

`include/dsp_config.h` e `include/model_params.h` são **gerados** por `ml/gen_headers.py`. `firmware/tools/dsp_cli.cpp` roda tudo no PC com o mesmo protocolo da serial.

### Python (`ml/`, `tests/`)

`ml/config.py` (constantes) · `ml/features.py` (referência das features) · `ml/build_dataset.py` (dados, splits, janelas) · `ml/train.py` (treino e escolha de limiar/N/M na validação) · `ml/export_onnx.py` · `ml/gen_headers.py` · `ml/evaluate.py` · `tests/parity_test.py` (Python × C++) · `tests/run_test.py` (harness).

## 3. Cada objeto de sincronização

| Objeto | O que protege | Problema que resolve | O que quebraria sem ele |
|---|---|---|---|
| `g_ring` (buffer circular 8×512) | dados de áudio entre T1 e T2 | os dois correm em ritmos diferentes; guarda ~256 ms de áudio | T1 esperaria T2 e o DMA perderia amostras |
| `blocks_ready` (semáforo de **contagem**, máx. 8) | a ordem "bloco pronto → T2 acorda" | T2 dorme sem gastar CPU; a contagem diz quantos blocos estão pendentes; `Give` que falha = overrun | T2 faria polling (CPU e atraso); sem como detectar overrun |
| `feature_q` (fila, 8 × `FeatureMsg`) | passagem de resultados T2→T3 por **cópia** | desacopla ritmos; se T3 atrasar, T2 descarta (`queue_drops`) em vez de travar | T2 travaria ou compartilharia memória sem proteção |
| `log_mutex` | `Serial` e o buffer `s_logbuf` | T3 e T4 escrevem; sem exclusão mútua as linhas se misturam | log corrompido (quebra o parser de `run_test.py`) |
| `stats_mutex` | `g_stats` (contadores e latências), `g_params` (GATE/THR/VOTE/MON) e o anel de janelas do monitor | T2/T3 escrevem estatísticas, T4 lê e altera parâmetros, T3 lê parâmetros | T4 leria valores "rasgados" (meio atualizados); T3 leria um limiar meio atualizado |
| atômicos `g_overruns`, `g_mutex_timeouts` | contadores tocados por T1 (e por quem falhar num mutex) | T1 **nunca** pode bloquear em mutex | usar mutex em T1 arriscaria travar a tarefa mais crítica |

**Regra anti-deadlock:** nenhuma tarefa segura os dois mutexes ao mesmo tempo (`log_S_line` pega `stats`, solta, e só depois pega `log`). Se algum dia precisar dos dois, a ordem é sempre `stats → log`.

## 4. Por que as prioridades são 5/3/2/1

- **T1 = 5 (core 0, sozinha):** o DMA do I2S enche buffers; se T1 demorar mais que ~128 ms para ler, amostras se perdem para sempre. É a única tarefa com prazo duro.
- **T2 = 3:** precisa terminar dentro de 32 ms (o passo entre janelas), senão o ring enche.
- **T3 = 2:** só consome; alguns ms de atraso no alerta não perdem dado.
- **T4 = 1:** só imprime, pode esperar.

**Se fossem invertidas** (ex.: T4 acima de T1): a impressão na serial (lenta) poderia impedir T1 de ler o DMA → overruns e áudio perdido. Se T3 > T2: T3 só roda depois que T2 produz algo, então a inversão pouco ajuda, mas prejudica T2 quando T3 estiver ocupada com log.

## 5. Pipeline de sinal (em linguagem simples)

- **Janela de 1024 amostras (64 ms)**: um "quadro" do som. Passo de 512: uma nova janela a cada 32 ms, sobrepostas em 50% para não perder um bipe que caia na emenda.
- **Remoção de DC**: o microfone tem um "nível médio" fora de zero; subtrair a média deixa só a vibração.
- **RMS / `rms_db`**: "volume" da janela. Serve de **gate**: abaixo de −50 dBFS é silêncio, nem roda o modelo.
- **Janela de Hann**: suaviza as bordas do quadro para a FFT não "inventar" frequências (vazamento espectral).
- **FFT**: converte 1024 amostras no tempo em 513 "quanto tem de cada frequência" (bins de 15,625 Hz).
- **Centroide espectral**: a "frequência média" ponderada pela energia (centro de massa do espectro). Voz tem centroide baixo (~centenas de Hz a 2 kHz), alarme de fumaça é um tom agudo (~3 kHz).
- **`band_ratio`**: fração da energia entre 2 e 4 kHz (onde o piezo do alarme mora).
- **`band_peakiness`**: dentro dessa banda, o pico domina? Um tom puro tem 1 pico forte; ruído espalha a energia.
- **`peak_freq_norm`**: em que frequência está o pico (normalizada por 8000 Hz).

## 6. Como o modelo nasceu e chegou ao ESP32

`ml/build_dataset.py` (clipes → janelas → 4 features + rótulo) → `ml/train.py` (`StandardScaler` + `LogisticRegression`; escolhe C, limiar e N de M **na validação**) → `models/model_params.json` → `ml/export_onnx.py` gera **`models/detector.onnx`** (entregável) e confere com o onnxruntime → `ml/gen_headers.py` grava `firmware/include/model_params.h` → `firmware/lib/dsp/model.cpp` calcula `z = Σ wᵢ (xᵢ − μᵢ)/σᵢ + b` e `p = 1/(1+e^{−z})`. O ESP32 **não** roda ONNX (pesado); roda a mesma conta em C++.

**Por que a paridade importa:** se o C++ calcular as features de um jeito ligeiramente diferente do Python do treino, o modelo recebe números que nunca viu e erra sem avisar. `tests/parity_test.py` compara features (Python float32 × C++), probabilidades (numpy, ONNX e C++) e decisões, nas mesmas janelas (inclusive WAVs reais). O maior erro medido foi ~1e-6.

## 7. Como a latência foi medida e o que cada número significa

Carimbos com `esp_timer_get_time()` (µs): `t_block_ready` (T1) → `t_feat_start`/`t_feat_done` (T2) → `t_recv`/`t_end` (T3). `t_sched` = espera até T2 começar; `t_feat` = custo do cálculo; `t_queue` = tempo na fila; `t_infer` = gate + modelo + decisão + LED; `t_total` = do bloco pronto ao LED; `t_decision` = da 1ª janela positiva do voto ao alerta. **Os números do ESP32 ainda estão PENDENTES** (só o PC foi medido, e isso não vale para o ESP32). Detalhes: `docs/latency_methodology.md`.

## 8. Roteiro da demo e o que dizer

1. Mostre o **diagrama** (`docs/diagrama_tarefas.svg`): "4 tarefas, prioridade 5/3/2/1; captura no núcleo 0, o resto no 1".
2. Ligue a placa e mostre o **autoteste** (LED pisca, barra de nível reage a uma palma).
3. Grave o `esp32dev`, abra o monitor e diga: "a cada 5 s a T4 imprime contadores e latências (e, com `python tests/calibrate.py`, dá para ajustar gate/limiar/voto ao vivo); `overruns=0` significa que a captura não perdeu nada".
4. (O limiar ao vivo é 0,99, não o 0,9 do treino: ver `docs/decisions.md` D11.) Toque o alarme do celular a ~40 cm: o **LED acende** (pode levar ~0,3–0,5 s: 64 ms de janela + voto de 6 de 8).
5. Faça palmas, fale, sacuda chaves: o LED **não** acende. Seja franca: sirene/despertador podem disparar (nos testes, 7,5% dos negativos difíceis).
6. Se der errado: mostre o log da serial salvo e rode `python tests/run_test.py --target native --demo-clip ...` para mostrar o pipeline decidindo janela a janela.

## 9. Doze perguntas de prova (respostas ancoradas no código)

**1) Por que a captura tem a prioridade mais alta?** Porque perder amostras é irreversível: o DMA do I2S tem 8 buffers × 256 quadros (`audio_capture.cpp`, ~128 ms). Se `t1_audio_capture` (`tasks.cpp`, prioridade `PRIO_T1_CAPTURE = 5`, core 0) não lê a tempo, o áudio se perde. Atrasar T2/T3 só aumenta a latência, não perde dado.

**2) Papel do semáforo entre T1 e T2, e por que não polling?** `blocks_ready` é um semáforo de contagem (máx. `RING_BLOCKS = 8`). T1 faz `xSemaphoreGive` a cada bloco; T2 (`xSemaphoreTake(..., portMAX_DELAY)`) dorme até haver bloco. Polling gastaria CPU, adicionaria atraso de amostragem e não daria a contagem de blocos pendentes; além disso o `Give` que falha é como detectamos overrun.

**3) Por que uma fila entre T2 e T3 e o que acontece quando enche?** `feature_q` (8 × `FeatureMsg`) desacopla os ritmos e passa dados **por cópia** (sem memória compartilhada). T2 usa `xQueueSend(..., 0)`: se cheia, descarta a mensagem e incrementa `queue_drops` em vez de esperar (não propaga atraso para a captura). Flags de controle (`FM_CLIP_START/END`) não se perdem: T2 as guarda em `pending_flags` e reenvia.

**4) Por que mutex e não semáforo binário (herança de prioridade)?** `stats_mutex` e `log_mutex` (`xSemaphoreCreateMutex`). Um mutex FreeRTOS **herda prioridade**: se T4 (prio 1) segura `stats_mutex` e T3 (prio 2) espera, T4 é temporariamente promovida e termina logo, evitando inversão de prioridade (uma tarefa média impedir a de baixa de soltar o lock). O semáforo binário não faz isso e não tem "dono".

**5) Onde há condição de corrida e como foi evitada?** (1) T1 escreve × T2 lê o ring: dono único de cada índice + semáforo + `seq[]` por slot; (2) Serial com T3 e T4: `log_mutex`; (3) estatísticas T2/T3 × T4: `stats_mutex`; (4) buzzer → microfone: `alert_suppressed()` ignora janelas por 300 ms após o toque + cooldown de 3 s (`decision_update`).

**6) O que é overrun e como é detectado?** T2 ficou 8 blocos atrasada; o ring está cheio. Em `t1_audio_capture`, `xSemaphoreGive` retorna falso (contagem já é 8) e T1 faz `g_overruns.fetch_add(1)`. O bloco mais antigo é sobrescrito; T2 percebe pelo `seq[]` em `ring_read` (`lost`/`torn_reads`) e descarta a janela descontínua.

**7) O que é o Spectral Centroid e por que separa o alarme da voz?** É a frequência média do espectro ponderada pela magnitude (`audio_features.cpp`: `Σ k·mag / Σ mag`, dividido por 8000). Voz concentra energia em frequências baixas/médias e espalhada; o alarme é um tom agudo (~3 kHz), então o centroide é alto e estável. Sozinho não basta (sirene também é aguda), por isso usamos também `band_ratio` e `band_peakiness` (na prática o modelo treinado dá mais peso a essas duas).

**8) Por que janela de 1024 a 16 kHz e qual a latência inerente?** 1024/16000 = 64 ms: resolução espectral de 15,625 Hz (separa bem tons em 2–4 kHz) e potência de 2 para a FFT radix-2. Passo de 512 (32 ms, 50% de sobreposição). Latência inerente = 64 ms (janela) + até 32 ms (passo) e, com o voto 6 de 8, no mínimo mais 5 passos (160 ms) até o alerta.

**9) Como o modelo roda no ESP32 se o entregável é `.onnx`?** O `.onnx` (`models/detector.onnx`) é o artefato validado com onnxruntime; os pesos vão para `model_params.h` (`ml/gen_headers.py`) e `model_predict` (`model.cpp`) refaz a conta em C++. `tests/parity_test.py` prova que ONNX e C++ dão a mesma probabilidade (erro ~1e-6).

**10) Por que dividir treino/teste por clipe?** Janelas consecutivas de um mesmo clipe são quase idênticas (50% de sobreposição); se algumas fossem para o treino e outras para o teste, o modelo "decoraria" o clipe e a acurácia seria falsamente alta (vazamento). `ml/build_dataset.py` divide por clipe (e os positivos reais, **por autor**; a fala, por locutor).

**11) Por que a acurácia ao vivo pode ser menor que a do teste?** Os positivos do teste são quase todos sintéticos e limpos; ao vivo há alto-falante de celular, sala, distância, ruído do ESP32, nível do INMP441 diferente (`I2S_SAMPLE_SHIFT`) e gate (`RMS_GATE_DB`) não calibrado. Só 3 alarmes reais no teste: 100% de recall neles é evidência fraca.

**12) Como se mediu a latência de cada etapa?** Cada mensagem carrega `t_block_ready_us` (T1), `t_feat_start_us`/`t_feat_done_us` (T2); T3 pega `t_recv` e `t_end` e calcula `t_sched`, `t_feat`, `t_queue`, `t_infer`, `t_total` (`t3_anomaly_detect`), guardando em `SystemStats` sob `stats_mutex`; T4 imprime média, p50, p95, máx. No ESP32: PENDENTE. No PC, `tests/run_test.py --target native` mede `t_feat` e `t_infer` com `std::chrono`.

## 10. Glossário

- **RTOS**: sistema operacional que garante prazos (prioridades, escalonamento previsível). Aqui, FreeRTOS.
- **ISR / DMA**: a ISR (rotina de interrupção) é acionada pelo hardware; o **DMA** copia os dados do I2S para a RAM sozinho, sem gastar CPU. A tarefa T1 "acorda" quando há dados.
- **Mutex**: trava com dono e herança de prioridade, para seções críticas.
- **Semáforo**: contador de sinalização; de **contagem**, conta eventos (blocos prontos).
- **Fila**: caixa de mensagens copiadas entre tarefas.
- **Overrun**: o produtor (T1) é mais rápido que o consumidor (T2) e o buffer enche.
- **Quantização 24→16 bits**: o INMP441 entrega 24 bits úteis em 32; deslocamos 16 (`I2S_SAMPLE_SHIFT`) para ter `int16` como nos WAVs do treino.
- **FFT**: algoritmo rápido que separa o sinal em frequências.
- **Hann**: janela que suaviza as bordas antes da FFT.
- **Centroide**: frequência média ponderada pela energia.
- **Gate**: porta de volume: abaixo de −50 dBFS a janela é considerada silêncio.
- **N de M**: alerta se N das últimas M janelas forem positivas (6 de 8), para ignorar picos isolados.
- **Cooldown**: tempo de espera (3 s) depois de um alerta antes de outro.
