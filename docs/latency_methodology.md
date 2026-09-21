# Metodologia de medição de latência

## O que é medido e onde

Todos os tempos usam `esp_timer_get_time()` (µs, contador de 64 bits do ESP32, resolução de 1 µs). Cada mensagem carrega os carimbos de tempo pela fila, então **T3 calcula todas as latências de uma janela** a partir de carimbos tomados em tarefas diferentes.

| Carimbo | Quem toma | Onde (código) |
|---|---|---|
| `t_block_ready_us` | T1 | `tasks.cpp::t1_audio_capture`, logo após `i2s_read` devolver o bloco que **completa** a janela |
| `t_feat_start_us` | T2 | `t2_feature_extract`, imediatamente antes de `features_compute` |
| `t_feat_done_us` | T2 | imediatamente depois de `features_compute` (antes de `xQueueSend`) |
| `t_recv` | T3 | `t3_anomaly_detect`, logo que `xQueueReceive` devolve |
| `t_end` | T3 | depois de gate + modelo + decisão **e** de acionar LED/buzzer |

| Latência | Definição | Interpretação |
|---|---|---|
| `t_window` (64 ms) e `HOP` (32 ms) | N/FS e HOP/FS | **Inerentes** à janela: o alarme só é "visto" depois de 1024 amostras. **Documentadas, não medidas.** |
| `t_sched` | `t_feat_start − t_block_ready` | Atraso de escalonamento: o bloco fica pronto (T1) até T2 começar a calcular. Inclui o `ring_read` (cópia de 1 KB). |
| `t_feat` | `t_feat_done − t_feat_start` | Custo do DC + RMS + Hann + FFT de 1024 + 4 features. |
| `t_queue` | `t_recv − t_feat_done` | Espera na fila até T3 receber. |
| `t_infer` | `t_end − t_recv` | Gate + regressão logística + regra N de M + acionamento do LED. |
| `t_total` | `t_end − t_block_ready` | Do bloco pronto até a decisão/LED. |
| `t_decision` | `t_end(alerta) − t_block_ready(1ª janela positiva do voto vencedor)` | Quanto tempo a **regra N de M** atrasa o alerta depois que o alarme começou a ser visto pelo modelo. Só existe em janelas de alerta. |

**Requisito de tempo real:** `t_sched + t_feat + t_queue + t_infer` deve ficar **bem abaixo de 32 ms** (o passo entre janelas); caso contrário o consumidor não acompanha o produtor e o ring/fila enchem (overrun / `queue_drops`).

## Estatísticas

Por etapa: média, p50, p95 e máximo. No firmware, `T4` calcula e imprime a cada 5 s sobre as **últimas 512 janelas** (≈ 16 s), com média e máximo acumulados; nos testes de bancada o `tests/run_test.py` calcula sobre **todas** as janelas coletadas (≥ 100 amostras). Contadores associados: `overruns`, `queue_drops`, `mutex_timeouts`, `torn_reads` e *stack high-water marks* (bytes livres por tarefa).

## Como reproduzir

```bash
# PC (alvo native): tempos do HOST, NÃO representam o ESP32
python tests/run_test.py --target native --split val
python tests/run_test.py --target native --split val --simulate-anomalies

# ESP32 (depois de gravar o esp32-test; NÃO VALIDADO em hardware até a aluna rodar)
python tests/run_test.py --target serial:/dev/ttyUSB0 --split val --max-per-type 10
```

Saídas em `docs/results/*.json|csv|png`, com carimbo de data e do alvo (`native` ou `esp32`). Um dispositivo falso (`tests/fake_esp32.py`) é rotulado `dispositivo-falso` e não deve ser citado como medição.

## Limitações da medição

- **No `native`**, só `t_feat` e `t_infer` existem (`std::chrono`, PC), `t_sched` e `t_queue` valem `-1` (não há RTOS). Servem para checar a lógica e o custo relativo, **não** o desempenho do ESP32.
- **Resolução:** 1 µs; a leitura de `esp_timer_get_time()` custa poucos µs por chamada, o que pode inflar levemente etapas muito curtas como `t_infer`.
- **Cache/flash:** a primeira execução após o boot pode ser mais lenta; o máximo captura isso, então p50/p95 são mais representativos que o máximo.
- **`t_total` não inclui** a latência da janela (64 ms) nem o tempo do DMA (o bloco só fica "pronto" quando o `i2s_read` retorna); a latência de ponta a ponta percebida por quem escuta é `t_window` + `t_decision` + `t_total`.
- No modo `esp32-test` o log por janela (`W,...`) é impresso por T3 e pode aumentar levemente `t_infer` de janelas seguintes por contenção de Serial; as medições "de produção" devem vir do resumo do T4 do `esp32dev`.

## Resultados

| Etapa | Alvo | Estado |
|---|---|---|
| `t_sched`, `t_feat`, `t_queue`, `t_infer`, `t_total`, `t_decision` no ESP32 | esp32 | **PENDENTE (medir no hardware)** |
| `t_feat`, `t_infer` no PC | native | medido: ver `docs/results/teste_*_native.json` (rotulado "host; não representa o ESP32") |
