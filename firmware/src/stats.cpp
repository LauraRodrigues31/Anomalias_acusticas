#include "stats.h"
#include <algorithm>

const char* const LAT_NAMES[LAT_COUNT] = {"t_sched", "t_feat", "t_queue", "t_infer", "t_total", "t_decision"};
std::atomic<uint32_t> g_overruns{0};
std::atomic<uint32_t> g_mutex_timeouts{0};

void stats_init() {
  g_overruns.store(0);
  g_mutex_timeouts.store(0);
}

void lat_add(LatStat* s, uint32_t us) {
  s->sum_us += us;
  if (us > s->max_us) s->max_us = us;
  s->samples[s->idx] = us;
  s->idx = (s->idx + 1) % LAT_SAMPLES;
  s->count++;
}

uint32_t lat_percentile(const LatStat& s, int pct, uint32_t* scratch) {
  const uint32_t n = s.count < LAT_SAMPLES ? s.count : LAT_SAMPLES;
  if (n == 0) return 0;
  for (uint32_t i = 0; i < n; i++) scratch[i] = s.samples[i];
  std::sort(scratch, scratch + n);
  uint32_t k = (uint32_t)((pct * (n - 1) + 50) / 100);
  return scratch[k];
}
