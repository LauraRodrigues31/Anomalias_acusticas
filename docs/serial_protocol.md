# Protocolo serial (esp32-test) e logs

Baud 921600, 8N1. O mesmo protocolo é usado pelo firmware (`-DAUDIO_SOURCE_SERIAL=1`) e por `firmware/tools/dsp_cli.cpp` (stdin/stdout no PC).

## Host → dispositivo

```
START <clip_id> <n_samples>\n
<n_samples amostras int16 little-endian, sem separador>
```

O firmware completa o último bloco de 512 amostras com zeros. O host pode enviar em **tempo real** (um bloco de 512 amostras = 1024 bytes a cada 32 ms) ou `--fast` (4×; o firmware faz contrapressão). Áudio int16 a 16 kHz = 32 KB/s; a serial a 921600 baud leva ~92 KB/s.

## Dispositivo → host (uma linha por evento, campos separados por vírgula)

| Linha | Formato |
|---|---|
| Janela | `W,<clip_id>,<win>,<t_block_ready_us>,<rms_db>,<cent>,<ratio>,<peakiness>,<pkfreq>,<prob>,<pos>,<t_sched_us>,<t_feat_us>,<t_queue_us>,<t_infer_us>,<t_total_us>` |
| Alerta | `A,<clip_id>,<win>,<t_alert_us>,<t_decision_us>` |
| Estatísticas | `S,<overruns>,<queue_drops>,<mutex_timeouts>,<hwm_t1>,<hwm_t2>,<hwm_t3>,<hwm_t4>` |
| Fim do clipe | `DONE <clip_id>` (depois de processar a última janela e do `S`) |
| Comentário | linhas iniciadas por `#` (T4, heartbeat a cada 5 s); o parser ignora |

- `prob = -1` quando a janela ficou abaixo do gate de RMS (modelo não rodou). `pos` é 0/1.
- `hwm_*` = *stack high-water mark* em **bytes livres** (ESP-IDF).
- Tempos: `t_block_ready_us` e demais são `esp_timer_get_time()` (µs desde o boot) no ESP32.

## Diferenças no alvo `native` (`dsp_cli`) — "host; não representam o ESP32"

- `t_feat_us` e `t_infer_us` vêm de `std::chrono` do PC. `t_sched_us` e `t_queue_us` = `-1` (não existem sem RTOS); `t_total_us = t_feat + t_infer`.
- `t_block_ready_us` e `t_alert_us` estão na **linha do tempo do áudio** (µs desde o início do clipe), e `t_decision_us` = alerta − 1ª janela positiva do voto vencedor, também em tempo de áudio.
- `S` sai com `-1` nos campos de stack.

## Comandos de serial do firmware de produção (`esp32dev`)

Só no `esp32dev` (o `esp32-test` usa a serial para o áudio). Lidos pela tarefa T4 a cada 100 ms; os valores mudam **só em RAM** (um reset volta aos valores iniciais: `dsp_config.h`/`model_params.h`, com o limiar sobrescrito por `LIVE_PROB_THRESHOLD` = 0,99 em `board_config.h`). Uma linha terminada em `\n`; maiúsculas/minúsculas indiferentes.

| Comando | Efeito | Resposta |
|---|---|---|
| `GATE <dBFS>` | gate de RMS, −120..0 | `OK GATE -45.0` ou `ERR ...` |
| `THR <p>` | limiar de probabilidade, (0, 1] | `OK THR 0.900` |
| `VOTE <n> <m>` | regra n de m, 1 ≤ n ≤ m ≤ 16 | `OK VOTE 6 8` |
| `MON 1` / `MON 0` | liga/desliga uma linha `M` por janela | `OK MON 1` |
| `STATS` | imprime as estatísticas agora | linhas `#`, `P,...` e `S,...` |

Linhas novas: `M,<janela>,<rms_db>,<prob>,<pos>,<votos_nas_últimas_M>,<alerta>` (uma por janela ≈ 31/s, entregue em rajadas a cada 100 ms; `prob = -1` se a janela ficou abaixo do gate; se T4 atrasar mais de ~0,5 s as janelas mais antigas são descartadas) e `P,<gate>,<thr>,<n>,<m>,<mon>` (parâmetros atuais, junto de cada bloco de estatísticas). O anel de janelas e os parâmetros ficam sob o `stats_mutex`; as respostas saem pelo `log_mutex` depois de soltar o outro.

`tests/calibrate.py` usa esses comandos (coleta com `GATE -120`, restaura no fim). O interpretador está em `firmware/lib/dsp/runtime_params.*` e é testado no PC; `dsp_cli --live` e `tests/fake_esp32.py --live` simulam o dispositivo com o mesmo código. **Não validado na placa.**

## Estado de validação

O lado do dispositivo (firmware) **não foi validado em hardware**. O lado do host do alvo serial foi exercitado apenas contra `tests/fake_esp32.py` (pty ligado ao `dsp_cli`); esses resultados saem rotulados `dispositivo-falso`.
