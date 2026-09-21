# Relatório técnico — Detector de anomalias acústicas (alarme de fumaça) em ESP32 + FreeRTOS

Aluna: Laura · Disciplina: Edge Computing (Inteli).

> **Aviso de honestidade.** Todo número de **acurácia offline** (seção 5) vem de execuções reais no PC (validação/teste do dataset da seção 4). Os números de **latência e robustez do ESP32** (seção 6.2) são **medições reais** no ESP32-D0WD-V3 com o firmware `esp32dev`, em 21/09/2026, numa execução em silêncio com alarmes ocasionais (**não** o pior caso contínuo). Os resultados **ao vivo** (seção 7) são uma **amostra pequena**, sem intervalo de confiança. Os tempos do PC (seção 6.3) são rotulados "host; não representam o ESP32".

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
| T4 `monitor` | 1 | 1 | a cada 100 ms trata os comandos de serial (`GATE`, `THR`, `VOTE`, `MON`, `STATS`) e o monitor por janela; a cada 5 s imprime estatísticas (sob mutex) e *stack high-water marks* |

### 2.1 Cada objeto de sincronização e por quê

| Objeto | Protege / faz | Sem ele… |
|---|---|---|
| **Buffer circular** (`g_ring`, 8 blocos × 512 `int16`) | absorve a diferença de ritmo entre captura (constante) e processamento (irregular); produtor e consumidor únicos, cada um dono de um índice | T2 leria blocos que T1 ainda está escrevendo, ou T1 esperaria T2 e perderia amostras do DMA |
| **Semáforo de contagem** `blocks_ready` (máx. 8) | T1 dá 1 por bloco; T2 pega 1 e **dorme** até haver dado. O `Give` que falha (contagem no máximo) é a **detecção de overrun** | T2 precisaria de *polling* (gasta CPU, latência de amostragem) e não haveria como saber quantos blocos estão pendentes |
| **Fila** `feature_q` (profundidade 8, `FeatureMsg` copiado) | desacopla T2 de T3; cópia por valor elimina compartilhamento de memória; `xQueueSend` com timeout 0: se cheia, descarta e conta (`queue_drops`) | T2 travaria esperando T3, propagando atraso até a captura |
| **Mutex** `log_mutex` | serializa a `Serial` (T3 e T4 escrevem) e o buffer de formatação | linhas de log intercaladas/corrompidas |
| **Mutex** `stats_mutex` | protege `SystemStats` (escrita por T2/T3, leitura por T4) | T4 leria contadores e amostras de latência no meio de uma atualização |

Escolhas relevantes:

- **Ajuste ao vivo sem regravar:** no `esp32dev`, T4 lê comandos de serial e altera, **em RAM**, o gate, o limiar e o voto (`RuntimeParams`, sob `stats_mutex`); T3 relê os parâmetros a cada janela. `MON 1` faz T3 empurrar cada janela num anel de 16 posições (também sob `stats_mutex`) que T4 drena a cada 100 ms para a Serial. Um reset volta aos padrões gerados do treino. Não validado na placa.

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

**Decisão:** janela positiva se `rms_db ≥ −50` e `p ≥ 0,9`; **alerta** se ao menos **6 das últimas 8** janelas forem positivas, respeitando cooldown de 3 s. LED por 2 s. **Limiar ao vivo:** no firmware de produção o valor inicial é 0,99 (override `LIVE_PROB_THRESHOLD`), calibrado ao vivo no ESP32 com `tests/calibrate.py` para que sirene, despertador e toque não disparem; **não** passou pelo conjunto de teste, as métricas da seção 5 são todas com 0,9, e a acurácia ao vivo com 0,99 só vale para os sons e a posição usados na calibração (`docs/decisions.md`, D11). Limiar (0,9) e N/M foram escolhidos **só na validação** (maior recall com FPR ≤ 3% por clipe). O voto padrão 3 de 5 da especificação, no mesmo limiar 0,9, dava na validação o mesmo recall (91,0%) com FPR de 4,3%, acima do orçamento de 3% que adotei; 6 de 8 dá FPR de 1,7% (só validação; ver `docs/decisions.md`, D7). Um MLP pequeno foi avaliado só na validação e descartado (D8).

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

Metodologia e definições em `docs/latency_methodology.md`. Latência inerente da janela: **64 ms** (janela) e **32 ms** (passo), documentadas, não medidas. Requisito de tempo real: `t_sched + t_feat + t_queue + t_infer` bem abaixo de 32 ms (o passo entre janelas).

### 6.1 Latência de projeto (consequência do desenho)

Com N=6 de M=8, o voto exige pelo menos 6 janelas positivas; o alerta mais rápido possível ocorre 5 passos (160 ms) depois da primeira janela positiva, somado aos 64 ms iniciais da janela. Isto é consequência do desenho, confirmado no PC (`t_decision` mínimo = 160 ms em tempo de áudio) e compatível com o que se mediu no ESP32 (`t_decision` p50 = 161.558 µs, seção 6.2).

### 6.2 ESP32: latência e robustez medidas (esp32dev, produção)

**Condições da medição (reais):** ESP32-D0WD-V3, firmware `esp32dev` (produção), 21/09/2026, valores lidos da linha `# t=1714s` do monitor serial (T4): **n = 53.570 janelas, ≈ 28,6 min**, em **silêncio com alarmes ocasionais**. **Não é o pior caso contínuo** (som constante, alarme sem pausa, log intenso).

| Etapa | média (µs) | p50 | p95 | máx |
|---|---|---|---|---|
| `t_sched` | 22 | 22 | 22 | 40 |
| `t_feat` | 1379 | 1377 | 1377 | 1603 |
| `t_queue` | 39 | 40 | 40 | 49 |
| `t_infer` | 10 | 9 | 11 | 153 |
| `t_total` | 1452 | 1448 | 1450 | 1818 |
| `t_decision` (n = 25 alertas) | 178126 | 161558 | 225471 | 225471 |

- **`t_total` é o processamento por janela** (do bloco pronto até a decisão/LED). **Não inclui** a duração da janela (64 ms) **nem** o passo de 32 ms, que são latência inerente do desenho (seção 6.1).
- **Orçamento de tempo real (32 ms = 32.000 µs):** `t_total` médio de 1452 µs ocupa ≈ 4,5% do passo; o máximo observado (1818 µs) ≈ 5,7%. `t_feat` (FFT e features) domina: 1379 µs de média. A soma das médias (22 + 1379 + 39 + 10 = 1450 µs) confere com o `t_total` (1452 µs) dentro de 2 µs. Nesta execução, portanto, o pipeline coube com folga no passo entre janelas.
- **`t_decision`** = da 1ª janela positiva do voto vencedor ao alerta: média ≈ 178,1 ms, p50 ≈ 161,6 ms, p95 = máx ≈ 225,5 ms. Com só n = 25, o p95 coincide com o máximo. O p50 está perto do mínimo de projeto (5 passos = 160 ms, seção 6.1).
- **Como ler os percentis:** o T4 calcula p50/p95 sobre as **últimas 512 janelas** (≈ 16 s, `LAT_SAMPLES`), enquanto média e máximo são acumulados sobre **todas** as janelas (n = 53.570). Para `t_decision` (n = 25 < 512) os percentis usam todas as amostras.

**Robustez (mesma linha `# t=1714s`):**

| Contador | Valor |
|---|---|
| `overruns` (T2 atrasada, ring cheio) | 0 |
| `queue_drops` (fila cheia) | 0 |
| `torn_reads` (leitura rasgada após overrun) | 0 |
| `mutex_timeouts` | 0 |

**Stack livre mínima observada** (*high-water mark*, bytes): T1 = 3396, T2 = 3404, T3 = 2500, T4 = 4228 (tamanhos configurados em `board_config.h`: 4096 / 4096 / 4096 / 6144). Nenhuma pilha chegou perto de acabar nesta execução.

Uso de memória do build `esp32dev` (real, do compilador, medido **antes** de acrescentar os comandos de ajuste ao vivo; refazer com `pio run`): RAM 26,5% (≈ 87 kB de 320 kB), flash 22,7% (≈ 298 kB de 1,3 MB).

**Bring-up e gravação (registro):** o bring-up do I2S exigiu **inverter `I2S_CHANNEL_SWAP` (0 → 1)** (canal do driver legado com `ONLY_LEFT`/`ONLY_RIGHT`); a gravação do firmware foi feita a **115200 baud** (`upload_speed` em `platformio.ini`).

### 6.3 PC (host; não representam o ESP32)

Split de teste, 94.760 janelas, `dsp_cli` nativo (`docs/results/teste_test_*_native.json`):

| Etapa | média (µs) | p50 | p95 | máx |
|---|---|---|---|---|
| `t_feat` (host) | 19,5 | 17 | 31 | 2289 |
| `t_infer` (host) | ≈ 0 | 0 | 0 | 17 |

`t_sched`/`t_queue` não existem no PC (sem RTOS). O ESP32 foi de fato **muito** mais lento nesta etapa (`t_feat` p50 = 1377 µs no ESP32 contra 17 µs no PC); **não extrapole** os números do PC.

## 7. Resultados ao vivo (amostra pequena)

**Isto é uma amostra pequena e informal, sem intervalo de confiança.** Não é uma avaliação: os itens abaixo não são acurácia/recall/FPR e **não** passaram pelo conjunto de teste do dataset (ver `docs/decisions.md`, D11). Parte do que se afirma aqui **não tem registro** (log serial, número de repetições, aparelho de origem); isso está dito item a item.

**Procedimento:** com o `esp32dev` gravado, o limiar de decisão foi calibrado **ao vivo** para **THR = 0,99** (voto 6 de 8 e gate −50 dBFS mantidos), com a sessão guiada `tests/calibrate.py`: 20 s por som (despertador, toque de ligação, sirene e alarme de fumaça tocados de alto-falante; também fala, palma e batida na mesa). O alarme de fumaça foi tocado **a partir de vídeos do YouTube**, em **dois aparelhos**: o **notebook** (a trilha `demo_track.wav` com `aplay` e um vídeo do YouTube) e o **celular** (teste final). A **distância de 30–50 cm era a pretendida; não foi medida.** Volume não registrado.

**O que foi observado, com o grau de evidência de cada item:**

| Item | Observação | Evidência / o que **não** foi registrado |
|---|---|---|
| Alarme de fumaça, **celular** (teste final) | o **LED acendeu** | verificado **só visualmente**; **não há log serial** e o **número de repetições não foi registrado** |
| Alarme de fumaça, **notebook** (`demo_track.wav` com `aplay` e vídeo do YouTube) | usado como fonte do alarme | nenhum resultado específico do notebook foi registrado aqui |
| Tempos de decisão do alarme | **≈ 161 a 193 ms** | vêm de **uma execução com log serial em que o aparelho de origem do alarme NÃO foi registrado** |
| Calibração de 20 s por som (`tests/calibrate.py`) | **0 alertas** nos negativos e **2 alertas** de alarme em 20 s | aparelho, volume e distância por som não registrados |
| fala, palma, batida na mesa | **não** dispararam | idem |
| despertador, toque de ligação, sirene | **não** dispararam **depois de calibrar THR = 0,99** (com o limiar de treino, 0,9, dispararam: motivo da calibração) | idem |

**Limites (importantes):**
- **Só vale para estes sons e estas condições** (vídeos do YouTube tocados de alto-falantes de notebook e celular, volume não registrado, distância pretendida de 30–50 cm **não medida**). Outro aparelho, volume, posição ou sala podem dar outro resultado.
- **Folga estreita:** o alarme chegou a probabilidade **0,998** e o limiar é **0,99**. Um alarme um pouco mais fraco ou distante pode cair abaixo do limiar e **não ser detectado**; a redução de recall com o limiar mais alto **não foi medida**.
- **Não é validação independente:** o limiar foi escolhido nos mesmos sons em que se observou o resultado (calibrado e avaliado na mesma amostra).
- **Falsos alertas na execução longa:** a execução de ≈ 28,6 min (seção 6.2) registrou 25 alertas no total (n de `t_decision`); **não** foi registrado quantos foram do alarme de fumaça e se houve falsos alertas.
- Nenhuma repetição sistemática (a tabela de 10 repetições do `HARDWARE_CHECKLIST.md` segue por fazer).

## 8. Discussão

**Dado sintético/limpo × microfone real.** A maior parte dos positivos é sintética e limpa: mesmo timbre do gerador, sem o filtro do alto-falante do celular, sem o microfone MEMS e sem sala real. Os 3 positivos reais do teste vêm de poucos autores; 100% de recall neles não é evidência forte. Espere queda de recall ao vivo, principalmente com o alarme tocado por um celular a 30–50 cm (resposta de frequência do alto-falante, reverberação, distorção). Na prática, ao vivo os negativos tonais (sirene, despertador, toque) dispararam com o limiar de treino e foi preciso subir o limiar para 0,99, com folga estreita (seção 7).

**Por que a acurácia ao vivo pode ser menor que a do teste:** distribuição diferente (sala, alto-falante, distância), ruído do próprio ESP32/fiação, deslocamento de bits (`I2S_SAMPLE_SHIFT`) e nível de sinal diferentes do treino, o gate de −50 dBFS que depende do ganho real do INMP441, e o fato de o teste offline ter só 3 alarmes reais.

**Limitações:** (i) só 4 features de uma janela; não há informação temporal de várias janelas (sirenes com varredura de frequência poderiam ser separadas por isso); (ii) poucos positivos reais; (iii) fala é isolada (palavras), não conversa; (iv) os "negativos difíceis" do ESC-50 são poucos (8 por categoria no teste); (v) o alvo serial do harness não foi validado em hardware.

**Riscos:** fiação/canal L/R errados (o autoteste existe para isso), o limiar calibrado em dados que não imitam o celular, latência de T3 com o log por janela no modo teste, e a corrida de I2S do driver legado se o overrun ocorrer (contadores existem para detectar).

**Trabalhos futuros:** coletar gravações reais no ambiente da demo; features temporais (modulação do padrão T3, 3 bipes + pausa) ou MFCC; MLP pequeno; calibrar o gate com o microfone real; usar o driver `i2s_std` do ESP-IDF 5; testar overrun de propósito (T2 atrasada) no hardware.

## 9. Fontes e atribuição

Licenças conferidas nos arquivos das próprias fontes (data/raw/…), não de memória. O uso neste trabalho é acadêmico e não comercial.

### 9.1 Positivos reais — Freesound (API oficial; 20 clipes mantidos após a curadoria)

Lista gerada de `data/raw/smoke_real/SOURCES.csv` menos `EXCLUDED.csv` (a licença é a que a API do Freesound devolveu para cada clipe: 15 CC0 e 5 CC-BY). Foi usado o *preview* mp3 convertido para 16 kHz mono. Os clipes CC-BY exigem atribuição ao autor, dada abaixo.

| Título | Autor (Freesound) | URL | Licença |
|---|---|---|---|
| Smoke Detector.wav | AaronGNP | <https://freesound.org/people/AaronGNP/sounds/44029/> | CC BY 4.0 |
| Smoke Detector Chirp 2 | Bloofrzo | <https://freesound.org/people/Bloofrzo/sounds/819807/> | CC0 1.0 |
| Smoke Detector Chirp 1 | Bloofrzo | <https://freesound.org/people/Bloofrzo/sounds/819808/> | CC0 1.0 |
| smoke detector fire alarm sound effect | Garuda1982 | <https://freesound.org/people/Garuda1982/sounds/530094/> | CC0 1.0 |
| smoke_alarm_piep_piep | Jan18101997 | <https://freesound.org/people/Jan18101997/sounds/170944/> | CC0 1.0 |
| LOUD Smoke Alarm unplug.wav | LiftPizzas | <https://freesound.org/people/LiftPizzas/sounds/557484/> | CC0 1.0 |
| Smoke detector alarm, distant neighboring room perspective.wav | SpliceSound | <https://freesound.org/people/SpliceSound/sounds/369847/> | CC0 1.0 |
| Smoke detector alarm, close perspective.wav | SpliceSound | <https://freesound.org/people/SpliceSound/sounds/369848/> | CC0 1.0 |
| Alarm_indoors_01 | Vitae-LI | <https://freesound.org/people/Vitae-LI/sounds/804505/> | CC BY 4.0 |
| Testing smoke detector (SoundAction 239) | alexarje | <https://freesound.org/people/alexarje/sounds/863217/> | CC BY 4.0 |
| ALRMElec_Smoke Detector Test Noise With Room_ladako_2m from mic.wav | ladako | <https://freesound.org/people/ladako/sounds/608738/> | CC0 1.0 |
| ALRMElec_Smoke Detector Test Noise_ladako_20cm from mic.wav | ladako | <https://freesound.org/people/ladako/sounds/608737/> | CC0 1.0 |
| ALRMElec_Smoke Detector Test Noise In Small Room_ladako_room reflections.wav | ladako | <https://freesound.org/people/ladako/sounds/608739/> | CC0 1.0 |
| First Alert Smoke Detector Test Beep 01 | loganzsound | <https://freesound.org/people/loganzsound/sounds/856777/> | CC0 1.0 |
| First Alert Smoke Detector 1m Away | loganzsound | <https://freesound.org/people/loganzsound/sounds/856776/> | CC0 1.0 |
| First Alert Smoke Detector 0.3m Away | loganzsound | <https://freesound.org/people/loganzsound/sounds/856775/> | CC0 1.0 |
| First Alert Smoke Detector Test Beep 02 | loganzsound | <https://freesound.org/people/loganzsound/sounds/856778/> | CC0 1.0 |
| smoke alarm | opalmirage | <https://freesound.org/people/opalmirage/sounds/666761/> | CC0 1.0 |
| Smoke Detector  Alarm | rayprice | <https://freesound.org/people/rayprice/sounds/155006/> | CC BY 3.0 |
| smoke_alarm.wav | wjoojoo | <https://freesound.org/people/wjoojoo/sounds/345497/> | CC BY 4.0 |

### 9.2 Positivos sintéticos — Hugging Face

*ShantyCam — AudioDet Synthetic Smoke-Alarm Clips* (`ShantyCam/audiodet-synth-smoke`, 250 clipes sintéticos): **CC-BY-4.0**, conforme o `README.md` do dataset (metadado `license: cc-by-4.0` e a seção "License", que pede a atribuição "ShantyCam — AudioDet Synthetic Smoke-Alarm Clips"). O outro conjunto sintético (`ml/gen_smoke_alarm.py`) é código deste projeto.

### 9.3 Negativos — ESC-50

K. J. Piczak, *ESC: Dataset for Environmental Sound Classification*, Proceedings of the 23rd ACM Conference on Multimedia, Brisbane, 2015, DOI 10.1145/2733373.2806390. Conforme `ESC-50/LICENSE`: o conjunto como um todo está sob **CC BY-NC 3.0** (uso não comercial); o subconjunto ESC-10 está sob CC BY 3.0; cada clipe deriva de uma gravação do Freesound com licença própria (CC0 ou CC-BY, autor e URL de origem listados clipe a clipe no próprio `ESC-50/LICENSE`, que não é reproduzido aqui). Como este trabalho é acadêmico, o uso é compatível com a cláusula NC; **não** use os dados/modelo em produto comercial sem rever essa licença.

### 9.4 Fala — mini_speech_commands

Excerto do *Speech Commands Dataset* usado em tutoriais do TensorFlow (8 palavras). **Licença: confirmar.** O `README.md` do excerto não declara a licença; ele apenas remete à documentação e à licença do dataset original (Speech Commands, do Google). Confirme na página do dataset original antes de publicar.

### 9.5 Outros

Ruído branco/rosa/marrom e todo o áudio de augmentation são gerados por código deste projeto. Bibliotecas: scikit-learn, skl2onnx, onnxruntime, NumPy/SciPy, Unity (ThrowTheSwitch) e PlatformIO/Arduino-ESP32 (cada uma com sua licença própria; **confirmar** ao redistribuir binários).

## 10. Referências

- Documentação Arduino-ESP32 2.0.x e ESP-IDF 4.4 (`driver/i2s.h`), FreeRTOS (mutex com herança de prioridade, semáforos de contagem, filas).
- Datasheet INMP441 (TDK InvenSense).
- K. J. Piczak, *ESC: Dataset for Environmental Sound Classification* (ESC-50), ACM Multimedia 2015, DOI 10.1145/2733373.2806390 (CC BY-NC 3.0).
- *Speech Commands Dataset* (Google; excerto `mini_speech_commands` do TensorFlow); licença a confirmar (ver seção 9.4).
- Hugging Face `ShantyCam/audiodet-synth-smoke` (CC-BY-4.0).
- Freesound (API v2), clipes CC0/CC-BY listados na seção 9.1.
- scikit-learn, skl2onnx, onnxruntime, Unity (ThrowTheSwitch), PlatformIO.
