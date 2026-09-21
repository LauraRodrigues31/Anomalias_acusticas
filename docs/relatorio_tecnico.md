# Relatório técnico — Detector de anomalias acústicas (alarme de fumaça) em ESP32 + FreeRTOS

Aluna: Laura · Disciplina: Edge Computing (Inteli).

> **Aviso de honestidade.** Todo número de **acurácia** abaixo vem de execuções reais no PC (conjuntos de validação/teste do dataset descrito na seção 4). Todo número de **latência do ESP32** está marcado `PENDENTE (medir no hardware)`: o firmware compila, mas ainda não foi gravado nem medido na placa. Os tempos do PC (seção 6.3) são rotulados "host; não representam o ESP32".

## 1. Aplicação prática e justificativa

**Problema:** uma pessoa surda ou com deficiência auditiva pode não ouvir o alarme de um detector de fumaça residencial. **Solução:** um dispositivo de borda que escuta o ambiente e acende um **LED** (alerta visual) quando reconhece o alarme (padrão de 3 bipes + pausa, tom de piezo entre ~2,8 e 3,5 kHz). Rodar na borda (ESP32) evita enviar áudio contínuo para a nuvem (privacidade, latência e custo) e funciona sem internet.

O que **não** deve disparar: fala, palmas, chaves, teclado, porta, toque/despertador de celular, sirene, buzina, ruído de sala. Sirene, buzina e despertador são os "negativos difíceis": também são sons tonais e altos.

## 2. Arquitetura RTOS

Quatro tarefas FreeRTOS (Arduino-ESP32 2.0.x sobre ESP-IDF 4.4). Diagrama completo: `docs/diagrama_tarefas.svg`.

| Tarefa | Prioridade | Núcleo | Função |
|---|---|---|---|
| T1 `audio_capture` | 5 | 0 | `i2s_read` bloqueante (DMA), converte 32→16 bits, grava no buffer circular, dá o semáforo |
| T2 `feature_extract` | 3 | 1 | espera o semáforo, monta a janela de 1024 amostras (2 blocos), calcula as features, envia à fila |
| T3 `anomaly_detect` | 2 | 1 | recebe da fila, gate de RMS, modelo, regra N de M, LED/buzzer, mede latências |
| T4 `monitor` | 1 | 1 | a cada 5 s imprime estatísticas (sob mutex), *stack high-water marks* |

### 2.1 Cada objeto de sincronização e por quê

| Objeto | Protege / faz | Sem ele… |
|---|---|---|
| **Buffer circular** (`g_ring`, 8 blocos × 512 `int16`) | absorve a diferença de ritmo entre captura (constante) e processamento (irregular); produtor e consumidor únicos, cada um dono de um índice | T2 leria blocos que T1 ainda está escrevendo, ou T1 esperaria T2 e perderia amostras do DMA |
| **Semáforo de contagem** `blocks_ready` (máx. 8) | T1 dá 1 por bloco; T2 pega 1 e **dorme** até haver dado. O `Give` que falha (contagem no máximo) é a **detecção de overrun** | T2 precisaria de *polling* (gasta CPU, latência de amostragem) e não haveria como saber quantos blocos estão pendentes |
| **Fila** `feature_q` (profundidade 8, `FeatureMsg` copiado) | desacopla T2 de T3; cópia por valor elimina compartilhamento de memória; `xQueueSend` com timeout 0: se cheia, descarta e conta (`queue_drops`) | T2 travaria esperando T3, propagando atraso até a captura |
| **Mutex** `log_mutex` | serializa a `Serial` (T3 e T4 escrevem) e o buffer de formatação | linhas de log intercaladas/corrompidas |
| **Mutex** `stats_mutex` | protege `SystemStats` (escrita por T2/T3, leitura por T4) | T4 leria contadores e amostras de latência no meio de uma atualização |

Escolhas relevantes:

- **Mutex e não semáforo binário** para as seções críticas: o mutex do FreeRTOS tem **herança de prioridade**, evitando inversão de prioridade (T4, de prioridade 1, segurando o `stats_mutex` enquanto T3 espera). Todas as tomadas de mutex têm **timeout** (50 ms); falha vira `mutex_timeouts`.
- **Anti-deadlock:** nenhuma tarefa segura os dois mutexes ao mesmo tempo (o código pega, solta e só então pega o outro). Se um dia for preciso, a ordem fixa é `stats → log`.
- **T1 nunca usa mutex nem `Serial.print`:** é a tarefa mais crítica e não pode bloquear. Seus contadores (`g_overruns`) e o `g_mutex_timeouts` são **atômicos**.
- **Overrun controlado:** quando o `Give` falha, T1 sobrescreve o bloco mais antigo. Como T2 poderia estar lendo exatamente esse bloco, cada slot tem um **número de sequência** (estilo seqlock): T1 marca o slot como "em escrita", grava e publica o id; T2 confere o id antes e depois de copiar e, se mudou, descarta o bloco (`torn_reads`) e descarta o bloco anterior da janela (janela descontínua).
- **Sem alocação dinâmica após a inicialização** (tudo em `rtos_start()`), buffers grandes estáticos (FFT, janela), **sem espera ocupada** (toda espera bloqueia: `i2s_read`, `xSemaphoreTake`, `xQueueReceive` com timeout, `vTaskDelay`), o que também evita o *watchdog*.
- **Prioridades 5/3/2/1:** perder amostras do DMA é irrecuperável (T1 no topo, sozinha no core 0); T2 produz o que T3 consome; T3 e T4 podem atrasar alguns ms sem perda.

### 2.2 Condições de corrida

1. T1 escrevendo enquanto T2 lê o ring → índices de dono único + semáforo de contagem + seqlock no overrun.
2. Vários escritores na Serial → `log_mutex`.
3. Estatísticas escritas por T2/T3 e lidas por T4 → `stats_mutex`.
4. Realimentação buzzer → microfone → janelas ignoradas durante o toque + 300 ms e cooldown de 3 s.

## 3. Processamento de sinal e modelo

Janela de **1024 amostras a 16 kHz (64 ms)**, passo **512 (32 ms)**, portanto 50% de sobreposição. Contrato exato em `docs/feature_spec.md`; Python (`ml/features.py`) e C++ (`firmware/lib/dsp`) são idênticos (teste de paridade).

Por janela: remove DC (o INMP441 tem offset), calcula RMS (só para o *gate* de −50 dBFS e log), aplica Hann periódica, FFT real e calcula: **centroide espectral** (normalizado), **razão de energia em 2–4 kHz**, **"peakiness" tonal** (pico da banda / energia da banda) e **frequência do pico**. O RMS **não** entra no modelo (evita depender do volume).

**Modelo:** regressão logística com padronização (4 pesos + viés), treinada com scikit-learn, exportada para `models/detector.onnx` (skl2onnx) e verificada com onnxruntime (erro máximo 2e-7 contra o scikit-learn). No ESP32 a inferência roda em **C++** com os pesos exportados para `firmware/include/model_params.h` (`z = Σ wᵢ·(xᵢ−μᵢ)/σᵢ + b; p = 1/(1+e^−z)`); o `.onnx` é o entregável e é validado contra o C++ por teste de paridade (erro máximo 3e-6 nas probabilidades).

**Decisão:** janela positiva se `rms_db ≥ −50` e `p ≥ 0,9`; **alerta** se ao menos **6 das últimas 8** janelas forem positivas, respeitando cooldown de 3 s. LED por 2 s. Limiar e N/M foram escolhidos **só na validação** (maior recall com FPR ≤ 3% por clipe). O voto padrão 3 de 5 da especificação, no mesmo limiar 0,9, dava na validação o mesmo recall (91,0%) com FPR de 4,3%, acima do orçamento de 3% que adotei; 6 de 8 dá FPR de 1,7% (só validação; ver `docs/decisions.md`, D7). Um MLP pequeno foi avaliado só na validação e descartado (D8).

## 4. Dados

Sem gravação própria; detalhes, fontes e licenças em `data/README.md`.

- **Positivos sintéticos:** 250 clipes do Hugging Face (`ShantyCam/audiodet-synth-smoke`, CC-BY-4.0) + 250 do gerador próprio (`ml/gen_smoke_alarm.py`: piezo 2,8–3,5 kHz, T3/T4/contínuo, harmônicos, deriva, reverberação).
- **Positivos reais:** 32 clipes do Freesound (API oficial, CC0/CC-BY) → **20** após curadoria (`ml/curate_real.py`: título sem relação, sem tom em 2–4 kHz ou abaixo do gate). Divididos **por autor**: 14 treino, 3 validação, 3 teste. Não há clipes em `smoke_real_manual/` nem `alarm_demo.wav`.
- **Negativos:** ESC-50 (2000 clipes, 50 classes; 400 "difíceis": `clock_alarm`, `siren`, `car_horn`, `church_bells`, `door_wood_knock`, `keyboard_typing`, `mouse_click`, `clapping`, `glass_breaking`, `crying_baby`), fala (`mini_speech_commands`, 5 palavras concatenadas por clipe, split por locutor) e ruído sintético branco/rosa/marrom.
- **Split por clipe** (nunca por janela): ESC-50 pelos folds oficiais (1–3 treino, 4 validação, 5 teste). Janelas de pausa entre bipes (energia da banda > 20 dB abaixo do máximo do clipe) são **excluídas** do treino. **Augmentation só no treino** (ganho, ruído SNR 0–30 dB, deslocamento, resposta de alto-falante, reverberação, alarme sobre fala, clipping).

## 5. Resultados de acurácia

Métrica por **clipe** = "houve pelo menos um ALERTA no clipe". Modelo final: limiar 0,9, N=6 de M=8, C=0,01 (`docs/results/*.json`, `*.png`). O conjunto de teste foi usado **uma vez**, depois de congelar o modelo, o limiar e o voto.

### 5.1 Validação (usada para escolher C, limiar e N/M)

| Tipo | n | Resultado |
|---|---|---|
| **Global** | 544 | recall 91,0% (71/78) · FPR 1,7% (8/466) |
| positivo sintético | 75 | recall 92,0% (69/75) |
| positivo real | 3 | recall 66,7% (2/3) |
| negativo comum | 386 | FPR 0,5% (2/386) |
| negativo difícil | 80 | FPR 7,5% (6/80) |

### 5.2 Teste (uma única vez)

| Tipo | n | Resultado |
|---|---|---|
| **Global** | 544 | **recall 93,6% (73/78) · FPR 2,6% (12/466) · acurácia 96,9%** |
| positivo sintético | 75 | recall 93,3% (70/75) |
| positivo real (Freesound) | 3 | recall 100% (3/3), **amostra minúscula**: o intervalo de confiança de 95% (Wilson) para 3/3 vai de ≈ 44% a 100% |
| positivo em `smoke_real_manual` | 0 | não há clipes |
| negativo comum | 386 | FPR 1,6% (6/386) |
| negativo difícil | 80 | **FPR 7,5% (6/80)** |

Por janela (teste): precisão 95,4%, recall 88,0%, FPR 0,84%. Matriz de confusão por clipe (global): TN 454, FP 12, FN 5, TP 73 (figura `docs/results/test_confusao_pr_*_host.png`).

**Leitura honesta:** as metas globais indicativas (recall ≥ 90%, FPR ≤ 5%) foram atingidas, **mas** o FPR isolado dos negativos difíceis (7,5%) fica acima de 5%: sirenes, buzinas e despertadores ainda disparam, o que é esperado com 4 features de uma única janela (um tom de sirene em 2–4 kHz é parecido com um alarme). Os falsos positivos em categorias não tonais (gato, galo, pássaros, ruídos) merecem atenção: o teste tem 8 clipes por categoria, então cada erro pesa 12,5% da categoria. O mesmo pipeline compilado em C++ (`dsp_cli`, via `tests/run_test.py --target native`) reproduziu **exatamente** os mesmos números de validação e de teste.

**Simulação de anomalias** (`--simulate-anomalies`, 40 cenas de 10 s com alarme sintético novo em instante conhecido sobre fundos de validação; PC): 40/40 detectadas em SNR 0, 5, 10 e 20 dB (10 cenas cada), atraso médio entre o início do alarme e o ALERTA (tempo de áudio) de 0,35 / 0,39 / 0,23 / 0,21 s. Atenção: o alarme é **sintético** e o SNR é aplicado sobre o fundo inteiro; não demonstra desempenho com um alarme real tocado por um alto-falante.

## 6. Análise de latência

Metodologia e definições em `docs/latency_methodology.md`. Latência inerente da janela: **64 ms** (janela) e **32 ms** (passo), documentadas, não medidas. Requisito de tempo real: `t_sched + t_feat + t_queue + t_infer` bem abaixo de 32 ms.

### 6.1 Latência de projeto (não medida)

Com N=6 de M=8, o voto exige pelo menos 6 janelas positivas; o alerta mais rápido possível ocorre 5 passos (160 ms) depois da primeira janela positiva, somado aos 64 ms iniciais da janela. Isto é consequência do desenho, confirmado no PC (`t_decision` mínimo = 160 ms em tempo de áudio).

### 6.2 ESP32 (tabela a preencher com medições reais)

| Etapa | média | p50 | p95 | máx |
|---|---|---|---|---|
| `t_sched` | PENDENTE (medir no hardware) | PENDENTE | PENDENTE | PENDENTE |
| `t_feat` | PENDENTE (medir no hardware) | PENDENTE | PENDENTE | PENDENTE |
| `t_queue` | PENDENTE (medir no hardware) | PENDENTE | PENDENTE | PENDENTE |
| `t_infer` | PENDENTE (medir no hardware) | PENDENTE | PENDENTE | PENDENTE |
| `t_total` | PENDENTE (medir no hardware) | PENDENTE | PENDENTE | PENDENTE |
| `t_decision` | PENDENTE (medir no hardware) | PENDENTE | PENDENTE | PENDENTE |

Contadores `overruns`, `queue_drops`, `mutex_timeouts` e *stack high-water marks*: **PENDENTE (medir no hardware)**. Uso de memória do build `esp32dev` (real, do compilador): RAM 26,5% (≈ 87 kB de 320 kB), flash 22,7% (≈ 298 kB de 1,3 MB).

### 6.3 PC (host; não representam o ESP32)

Split de teste, 94.760 janelas, `dsp_cli` nativo (`docs/results/teste_test_*_native.json`):

| Etapa | média (µs) | p50 | p95 | máx |
|---|---|---|---|---|
| `t_feat` (host) | 19,5 | 17 | 31 | 2289 |
| `t_infer` (host) | ≈ 0 | 0 | 0 | 17 |

`t_sched`/`t_queue` não existem no PC (sem RTOS). O ESP32 (240 MHz, FPU de precisão simples, FFT de 1024 pontos complexa em `float`) será **muito** mais lento que um PC; **não extrapole** estes números.

## 7. Discussão

**Dado sintético/limpo × microfone real.** A maior parte dos positivos é sintética e limpa: mesmo timbre do gerador, sem o filtro do alto-falante do celular, sem o microfone MEMS e sem sala real. Os 3 positivos reais do teste vêm de poucos autores; 100% de recall neles não é evidência forte. Espere queda de recall ao vivo, principalmente com o alarme tocado por um celular a 30–50 cm (resposta de frequência do alto-falante, reverberação, distorção).

**Por que a acurácia ao vivo pode ser menor que a do teste:** distribuição diferente (sala, alto-falante, distância), ruído do próprio ESP32/fiação, deslocamento de bits (`I2S_SAMPLE_SHIFT`) e nível de sinal diferentes do treino, o gate de −50 dBFS que depende do ganho real do INMP441, e o fato de o teste offline ter só 3 alarmes reais.

**Limitações:** (i) só 4 features de uma janela; não há informação temporal de várias janelas (sirenes com varredura de frequência poderiam ser separadas por isso); (ii) poucos positivos reais; (iii) fala é isolada (palavras), não conversa; (iv) os "negativos difíceis" do ESC-50 são poucos (8 por categoria no teste); (v) o alvo serial do harness não foi validado em hardware.

**Riscos:** fiação/canal L/R errados (o autoteste existe para isso), o limiar calibrado em dados que não imitam o celular, latência de T3 com o log por janela no modo teste, e a corrida de I2S do driver legado se o overrun ocorrer (contadores existem para detectar).

**Trabalhos futuros:** coletar gravações reais no ambiente da demo; features temporais (modulação do padrão T3, 3 bipes + pausa) ou MFCC; MLP pequeno; calibrar o gate com o microfone real; usar o driver `i2s_std` do ESP-IDF 5; testar overrun de propósito (T2 atrasada) no hardware.

## 8. Referências

- Documentação Arduino-ESP32 2.0.x e ESP-IDF 4.4 (`driver/i2s.h`), FreeRTOS (mutex com herança de prioridade, semáforos de contagem, filas).
- Datasheet INMP441 (TDK InvenSense).
- K. Piczak, *ESC: Dataset for Environmental Sound Classification* (ESC-50), ACM Multimedia 2015 (CC BY-NC 3.0).
- P. Warden, *Speech Commands* (excerto `mini_speech_commands`, TensorFlow; CC BY 4.0).
- Hugging Face `ShantyCam/audiodet-synth-smoke` (CC-BY-4.0).
- Freesound (API v2), clipes CC0/CC-BY listados em `data/raw/smoke_real/SOURCES.csv` (não versionado; citar os autores CC-BY ao publicar).
- scikit-learn, skl2onnx, onnxruntime, Unity (ThrowTheSwitch), PlatformIO.
