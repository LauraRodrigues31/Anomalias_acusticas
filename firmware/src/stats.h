// Estatísticas do sistema. Contadores tocados por T1 (que nunca pode bloquear) são atômicos;
// o resto fica em SystemStats, protegido por stats_mutex.
#pragma once
#include <stdint.h>
#include <atomic>
#include "board_config.h"

#define LAT_SAMPLES 512   // janela deslizante p/ percentis (últimas 512 janelas ≈ 16 s)

enum LatKind { LAT_SCHED, LAT_FEAT, LAT_QUEUE, LAT_INFER, LAT_TOTAL, LAT_DECISION, LAT_COUNT };
extern const char* const LAT_NAMES[LAT_COUNT];

struct LatStat {
  uint64_t sum_us;
  uint32_t count;
  uint32_t max_us;
  uint32_t idx;
  uint32_t samples[LAT_SAMPLES];  // buffer circular das últimas amostras
};

struct SystemStats {
  uint32_t blocks;         // blocos consumidos por T2
  uint32_t windows;        // janelas com features calculadas
  uint32_t windows_pos;    // janelas positivas (após gate + modelo)
  uint32_t windows_gated;  // janelas abaixo do gate de RMS
  uint32_t alerts;
  uint32_t queue_drops;    // fila cheia: T2 descartou a mensagem
  uint32_t torn_reads;     // blocos perdidos/rasgados após overrun (visto por T2)
  LatStat lat[LAT_COUNT];
};

// Contadores que não passam pelo mutex.
extern std::atomic<uint32_t> g_overruns;        // T1: give falhou (ring cheio)
extern std::atomic<uint32_t> g_mutex_timeouts;  // qualquer tarefa: falha ao pegar mutex

void stats_init();
void lat_add(LatStat* s, uint32_t us);
// Percentil (0..100) sobre as amostras guardadas; usa `scratch` (LAT_SAMPLES) como área de trabalho.
uint32_t lat_percentile(const LatStat& s, int pct, uint32_t* scratch);
