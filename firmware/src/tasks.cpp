#include "tasks.h"
#include <Arduino.h>
#include <esp_timer.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "alert.h"
#include "audio_capture.h"
#include "audio_features.h"
#include "decision.h"
#include "model.h"
#include "model_params.h"
#include "ring.h"
#include "stats.h"

// =============================================================================================
// Objetos compartilhados. Cada um existe por um motivo (ver docs/diagrama_tarefas.svg):
//   g_ring        buffer circular T1 -> T2 (produtor e consumidor únicos)
//   blocks_ready  semáforo de CONTAGEM: T1 dá 1 por bloco, T2 pega 1 (acorda T2 sem polling;
//                 a contagem máxima RING_BLOCKS detecta overrun quando o Give falha)
//   feature_q     fila T2 -> T3 (desacopla ritmos; cópia por valor evita corrida)
//   log_mutex     serializa Serial (T3 e T4 escrevem) e protege o buffer de formatação
//   stats_mutex   protege SystemStats (escrita T2/T3, leitura T4). MUTEX (não semáforo binário)
//                 por causa da HERANÇA DE PRIORIDADE.
// REGRA ANTI-DEADLOCK: nenhuma tarefa segura os dois mutexes ao mesmo tempo. Se algum dia
// for preciso, a ordem fixa é stats_mutex -> log_mutex. Toda tomada tem timeout.
// =============================================================================================
static Ring g_ring;
static SemaphoreHandle_t blocks_ready;
static QueueHandle_t feature_q;
static SemaphoreHandle_t log_mutex;
static SemaphoreHandle_t stats_mutex;

static SystemStats g_stats;   // protegido por stats_mutex
static SystemStats g_snap;    // cópia local de T4 (fora do mutex)
static TaskHandle_t h_t1, h_t2, h_t3, h_t4;

static inline int64_t now_us() { return esp_timer_get_time(); }

// ---- helpers de mutex (sempre com timeout; falha vira contador) ------------------------------
static bool take(SemaphoreHandle_t m) {
  if (xSemaphoreTake(m, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) == pdTRUE) return true;
  g_mutex_timeouts.fetch_add(1);
  return false;
}

// printf serializado. O buffer estático é protegido pelo próprio log_mutex.
static char s_logbuf[384];
static void log_printf(const char* fmt, ...) {
  if (!take(log_mutex)) return;
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(s_logbuf, sizeof s_logbuf, fmt, ap);
  va_end(ap);
  if (n > 0) Serial.write((const uint8_t*)s_logbuf, n < (int)sizeof s_logbuf ? n : sizeof s_logbuf - 1);
  xSemaphoreGive(log_mutex);
}

// Linha "S,..." (contadores + stack high-water marks, em bytes livres).
static void log_S_line() {
  uint32_t drops = 0;
  if (take(stats_mutex)) {           // 1º stats...
    drops = g_stats.queue_drops;
    xSemaphoreGive(stats_mutex);     // ...solta...
  }
  log_printf("S,%u,%u,%u,%u,%u,%u,%u\n", (unsigned)g_overruns.load(), (unsigned)drops,  // ...depois log
             (unsigned)g_mutex_timeouts.load(), (unsigned)uxTaskGetStackHighWaterMark(h_t1),
             (unsigned)uxTaskGetStackHighWaterMark(h_t2), (unsigned)uxTaskGetStackHighWaterMark(h_t3),
             (unsigned)uxTaskGetStackHighWaterMark(h_t4));
}

// =============================================================================================
// T1 — captura (prioridade 5, core 0)
// Mais alta porque perder amostras do DMA é irrecuperável, enquanto atrasar T2/T3 só aumenta
// a latência. Bloqueia no i2s_read (o driver acorda a tarefa por interrupção de DMA).
// NÃO usa Serial.print nem mutex (um mutex poderia bloquear a tarefa mais crítica).
// =============================================================================================
static void t1_audio_capture(void*) {
  static int16_t blk[DSP_HOP];   // estático: pilha pequena
  BlockMeta meta;
  uint32_t id = 0;
  for (;;) {
    if (!audio_read_block(blk, &meta)) {
      vTaskDelay(pdMS_TO_TICKS(1));
      continue;
    }
#if AUDIO_SOURCE_SERIAL
    // Modo de teste: o host pode enviar mais rápido que o tempo real. Contrapressão em vez de
    // overrun, para que o teste seja determinístico. (Bloqueia com delay, não com busy-wait.)
    while (uxSemaphoreGetCount(blocks_ready) >= RING_BLOCKS) vTaskDelay(1);
#endif
    const int64_t t_ready = now_us();
    id++;
    ring_write(&g_ring, id, blk, meta, t_ready);
    // Give falhou => contagem já está no máximo => T2 está RING_BLOCKS blocos atrasada.
    // ring_write já sobrescreveu o bloco mais antigo (de forma controlada, ver ring.h).
    if (xSemaphoreGive(blocks_ready) != pdTRUE) g_overruns.fetch_add(1);
  }
}

// =============================================================================================
// T2 — extração de features (prioridade 3, core 1)
// Média: só precisa acabar dentro de HOP (32 ms). Menor que T1 (não pode atrasar a captura) e
// maior que T3 (T3 só consome o que T2 produz).
// =============================================================================================
static void t2_feature_extract(void*) {
  static int16_t win[DSP_N];     // [bloco anterior | bloco atual]
  static Features f;
  uint32_t rd_id = 1, win_idx = 0, clip_id = 0, pending_flags = 0;
  bool have_prev = false;
  BlockMeta m;
  int64_t t_ready = 0;
  for (;;) {
    xSemaphoreTake(blocks_ready, portMAX_DELAY);   // bloqueia sem CPU até haver bloco

    uint32_t lost = 0;
    const bool ok = ring_read(&g_ring, &rd_id, &win[DSP_HOP], &m, &t_ready, &lost);
    // se rasgou/pulou, a janela deixa de ser contínua: descarta o bloco anterior
    if (lost) have_prev = false;
    uint32_t drop_inc = 0;
    if (!ok) {
      if (take(stats_mutex)) {
        g_stats.torn_reads += lost;
        xSemaphoreGive(stats_mutex);
      }
      continue;
    }

    uint8_t flags = (uint8_t)pending_flags;
    pending_flags = 0;
    if (m.flags & BLK_CLIP_START) {
      have_prev = false;
      win_idx = 0;
      clip_id = m.clip_id;
      flags |= FM_CLIP_START;
    }
    if (m.flags & BLK_CLIP_END) flags |= FM_CLIP_END;

    FeatureMsg msg;
    memset(&msg, 0, sizeof msg);
    msg.clip_id = clip_id;
    msg.t_block_ready_us = t_ready;
    if (have_prev) {
      msg.t_feat_start_us = now_us();
      features_compute(win, &f);
      msg.t_feat_done_us = now_us();
      msg.window_id = win_idx++;
      msg.rms_db = f.rms_db;
      features_to_vector(f, msg.feat);
    } else {
      flags |= FM_NOWINDOW;
    }
    msg.flags = flags;
    // a metade "anterior" da próxima janela é o bloco atual
    memcpy(win, &win[DSP_HOP], sizeof(int16_t) * DSP_HOP);
    have_prev = true;

    // timeout 0: T2 nunca espera T3; fila cheia => descarta e conta.
    if (xQueueSend(feature_q, &msg, 0) != pdTRUE) {
      drop_inc = 1;
      pending_flags = flags & (FM_CLIP_START | FM_CLIP_END);   // controle não pode se perder
    }
    if (take(stats_mutex)) {
      g_stats.blocks++;
      if (!(flags & FM_NOWINDOW)) g_stats.windows++;
      g_stats.queue_drops += drop_inc;
      g_stats.torn_reads += lost;
      xSemaphoreGive(stats_mutex);
    }
  }
}

// =============================================================================================
// T3 — detecção (prioridade 2, core 1)
// Mais baixa entre as de processamento: alertar com uns ms de atraso não perde dado, mas T3
// atrasar T2 encheria o ring. A fila (com timeout de 20 ms) também serve para apagar LED/buzzer
// no tempo certo sem busy-wait.
// =============================================================================================
static void t3_anomaly_detect(void*) {
  FeatureMsg m;
  DecisionState ds;
  decision_reset(&ds);
  for (;;) {
    const BaseType_t got = xQueueReceive(feature_q, &m, pdMS_TO_TICKS(20));
    alert_update((uint32_t)(now_us() / 1000));
    if (!got) continue;
    const int64_t t_recv = now_us();

    if (m.flags & FM_CLIP_START) decision_reset(&ds);

    if (!(m.flags & FM_NOWINDOW)) {
      // --- gate + modelo + decisão ---
      float prob = -1.0f;
      bool pos = false;
      const bool gated = m.rms_db < DSP_RMS_GATE_DB;
      if (!gated) {
        prob = model_predict(m.feat);
        pos = prob >= PROB_THRESHOLD;
      }
      const uint32_t now_ms = (uint32_t)(t_recv / 1000);
      int64_t first_pos_us = 0;
      const bool alert = decision_update(&ds, pos, now_ms, m.t_block_ready_us, alert_suppressed(now_ms), &first_pos_us);
      if (alert) alert_trigger(now_ms);
      const int64_t t_end = now_us();

      const uint32_t t_sched = (uint32_t)(m.t_feat_start_us - m.t_block_ready_us);
      const uint32_t t_feat = (uint32_t)(m.t_feat_done_us - m.t_feat_start_us);
      const uint32_t t_queue = (uint32_t)(t_recv - m.t_feat_done_us);
      const uint32_t t_infer = (uint32_t)(t_end - t_recv);
      const uint32_t t_total = (uint32_t)(t_end - m.t_block_ready_us);
      const uint32_t t_decision = alert ? (uint32_t)(t_end - first_pos_us) : 0;

      if (take(stats_mutex)) {
        lat_add(&g_stats.lat[LAT_SCHED], t_sched);
        lat_add(&g_stats.lat[LAT_FEAT], t_feat);
        lat_add(&g_stats.lat[LAT_QUEUE], t_queue);
        lat_add(&g_stats.lat[LAT_INFER], t_infer);
        lat_add(&g_stats.lat[LAT_TOTAL], t_total);
        if (gated) g_stats.windows_gated++;
        if (pos) g_stats.windows_pos++;
        if (alert) {
          g_stats.alerts++;
          lat_add(&g_stats.lat[LAT_DECISION], t_decision);
        }
        xSemaphoreGive(stats_mutex);
      }
#if AUDIO_SOURCE_SERIAL
      // Log por janela só no modo de teste (custo de Serial em T3; T1 nunca imprime).
      log_printf("W,%u,%u,%lld,%.3f,%.6f,%.6f,%.6f,%.6f,%.6f,%d,%u,%u,%u,%u,%u\n", (unsigned)m.clip_id,
                 (unsigned)m.window_id, (long long)m.t_block_ready_us, m.rms_db, m.feat[0], m.feat[1], m.feat[2],
                 m.feat[3], prob, pos ? 1 : 0, (unsigned)t_sched, (unsigned)t_feat, (unsigned)t_queue,
                 (unsigned)t_infer, (unsigned)t_total);
#endif
      if (alert)
        log_printf("A,%u,%u,%lld,%u\n", (unsigned)m.clip_id, (unsigned)m.window_id, (long long)t_end,
                   (unsigned)t_decision);
    }
#if AUDIO_SOURCE_SERIAL
    if (m.flags & FM_CLIP_END) {
      log_S_line();
      log_printf("DONE %u\n", (unsigned)m.clip_id);
    }
#endif
  }
}

// =============================================================================================
// T4 — monitor (prioridade 1, core 1): a cada 5 s copia as estatísticas sob mutex e imprime.
// Copiar e soltar o mutex ANTES de imprimir mantém a seção crítica curta (T2/T3 esperam pouco).
// =============================================================================================
static void t4_monitor(void*) {
  static uint32_t scratch[LAT_SAMPLES];
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(STATS_PERIOD_MS));
    if (take(stats_mutex)) {
      memcpy(&g_snap, &g_stats, sizeof g_snap);
      xSemaphoreGive(stats_mutex);
    } else {
      continue;
    }
    log_printf("# t=%lus blocks=%u win=%u pos=%u gated=%u alerts=%u overruns=%u drops=%u torn=%u mtx_to=%u\n",
               (unsigned long)(millis() / 1000), (unsigned)g_snap.blocks, (unsigned)g_snap.windows,
               (unsigned)g_snap.windows_pos, (unsigned)g_snap.windows_gated, (unsigned)g_snap.alerts,
               (unsigned)g_overruns.load(), (unsigned)g_snap.queue_drops, (unsigned)g_snap.torn_reads,
               (unsigned)g_mutex_timeouts.load());
    for (int k = 0; k < LAT_COUNT; k++) {
      const LatStat& L = g_snap.lat[k];
      if (!L.count) continue;
      log_printf("# %-10s n=%u mean=%uus p50=%uus p95=%uus max=%uus\n", LAT_NAMES[k], (unsigned)L.count,
                 (unsigned)(L.sum_us / L.count), (unsigned)lat_percentile(L, 50, scratch),
                 (unsigned)lat_percentile(L, 95, scratch), (unsigned)L.max_us);
    }
    log_printf("# stack livre (bytes) T1=%u T2=%u T3=%u T4=%u\n", (unsigned)uxTaskGetStackHighWaterMark(h_t1),
               (unsigned)uxTaskGetStackHighWaterMark(h_t2), (unsigned)uxTaskGetStackHighWaterMark(h_t3),
               (unsigned)uxTaskGetStackHighWaterMark(h_t4));
    log_S_line();
  }
}

void rtos_start() {
  stats_init();
  memset(&g_stats, 0, sizeof g_stats);
  ring_init(&g_ring);
  alert_init();
  if (!audio_init()) {
    Serial.println("# ERRO: falha ao iniciar a fonte de audio (I2S)");
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
  }
  // Toda alocação dinâmica do programa acontece aqui, uma vez.
  blocks_ready = xSemaphoreCreateCounting(RING_BLOCKS, 0);
  feature_q = xQueueCreate(FEATURE_Q_DEPTH, sizeof(FeatureMsg));
  log_mutex = xSemaphoreCreateMutex();
  stats_mutex = xSemaphoreCreateMutex();
  configASSERT(blocks_ready && feature_q && log_mutex && stats_mutex);

  // Cria consumidores antes do produtor para não perder os primeiros blocos.
  xTaskCreatePinnedToCore(t4_monitor, "T4_monitor", STACK_T4, nullptr, PRIO_T4_MONITOR, &h_t4, CORE_T4);
  xTaskCreatePinnedToCore(t3_anomaly_detect, "T3_detect", STACK_T3, nullptr, PRIO_T3_DETECT, &h_t3, CORE_T3);
  xTaskCreatePinnedToCore(t2_feature_extract, "T2_features", STACK_T2, nullptr, PRIO_T2_FEATURES, &h_t2, CORE_T2);
  xTaskCreatePinnedToCore(t1_audio_capture, "T1_capture", STACK_T1, nullptr, PRIO_T1_CAPTURE, &h_t1, CORE_T1);
}
