// Executável nativo: lê o mesmo protocolo da serial do firmware (stdin) e escreve linhas
// W/A/S/DONE em stdout (docs/serial_protocol.md).
//   entrada:  "START <clip_id> <n_samples>\n" + n_samples int16 little-endian
// Tempos t_feat e t_infer usam std::chrono e são do HOST: NÃO representam o ESP32.
// t_sched e t_queue não existem no PC (sem RTOS) e saem como -1.
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <chrono>
#include <vector>
#include "fft.h"
#include "audio_features.h"
#include "model.h"
#include "decision.h"
#include "model_params.h"

using clk = std::chrono::steady_clock;
static inline int64_t us_between(clk::time_point a, clk::time_point b) {
  return std::chrono::duration_cast<std::chrono::microseconds>(b - a).count();
}

int main() {
  setvbuf(stdout, nullptr, _IOFBF, 1 << 16);
  dsp_init();
  char line[256];
  while (fgets(line, sizeof line, stdin)) {
    char id[128];
    long n = 0;
    if (sscanf(line, "START %127s %ld", id, &n) != 2) continue;
    std::vector<int16_t> pcm(n);
    if (n > 0 && fread(pcm.data(), 2, n, stdin) != (size_t)n) return 1;
    // completa o último bloco com zeros (igual ao firmware)
    const long nblk = (n + DSP_HOP - 1) / DSP_HOP;
    pcm.resize(nblk * DSP_HOP, 0);

    DecisionState ds;
    decision_reset(&ds);
    long nalerts = 0;
    for (long w = 0; w + 1 < nblk; w++) {
      // instante (áudio) em que o bloco que completa a janela fica pronto
      const int64_t t_ready_us = (int64_t)(w * DSP_HOP + DSP_N) * 1000000LL / DSP_FS;
      Features f;
      auto t0 = clk::now();
      features_compute(&pcm[w * DSP_HOP], &f);
      auto t1 = clk::now();
      float prob = -1.0f;
      bool pos = false;
      if (f.rms_db >= DSP_RMS_GATE_DB) {
        float v[MODEL_N_FEATURES];
        features_to_vector(f, v);
        prob = model_predict(v);
        pos = prob >= PROB_THRESHOLD;
      }
      int64_t first = 0;
      const bool alert = decision_update(&ds, pos, (uint32_t)(t_ready_us / 1000), t_ready_us, false, &first);
      auto t2 = clk::now();
      const int64_t t_feat = us_between(t0, t1), t_infer = us_between(t1, t2);
      printf("W,%s,%ld,%lld,%.3f,%.6f,%.6f,%.6f,%.6f,%.6f,%d,-1,%lld,-1,%lld,%lld\n", id, w,
             (long long)t_ready_us, f.rms_db, f.centroid_norm, f.band_ratio, f.band_peakiness,
             f.peak_freq_norm, prob, pos ? 1 : 0, (long long)t_feat, (long long)t_infer,
             (long long)(t_feat + t_infer));
      if (alert) {
        nalerts++;
        // no PC, t_alert e t_decision estão na linha do tempo do ÁUDIO
        printf("A,%s,%ld,%lld,%lld\n", id, w, (long long)t_ready_us, (long long)(t_ready_us - first));
      }
    }
    printf("S,0,0,0,-1,-1,-1,-1\n");
    printf("DONE %s\n", id);
    fflush(stdout);
  }
  return 0;
}
