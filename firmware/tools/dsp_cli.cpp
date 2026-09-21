// Executável nativo: lê o mesmo protocolo da serial do firmware (stdin) e escreve linhas
// W/A/S/DONE em stdout (docs/serial_protocol.md).
//   entrada:  "START <clip_id> <n_samples>\n" + n_samples int16 little-endian
// Modo `--live <arquivo.raw> [velocidade]`: simula o firmware de PRODUÇÃO ao vivo (áudio em laço,
// comandos GATE/THR/VOTE/MON/STATS pela stdin, linhas M/P/S/A), usando o MESMO interpretador de
// comandos e a mesma decisão do firmware. Serve para testar tests/calibrate.py sem placa.
// Tempos t_feat e t_infer usam std::chrono e são do HOST: NÃO representam o ESP32.
// t_sched e t_queue não existem no PC (sem RTOS) e saem como -1.
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <stdlib.h>
#include <string>
#include <chrono>
#include <thread>
#include <vector>
#include <poll.h>
#include <unistd.h>
#include "fft.h"
#include "audio_features.h"
#include "model.h"
#include "decision.h"
#include "model_params.h"
#include "runtime_params.h"
#include "board_config.h"

using clk = std::chrono::steady_clock;
static inline int64_t us_between(clk::time_point a, clk::time_point b) {
  return std::chrono::duration_cast<std::chrono::microseconds>(b - a).count();
}


// ---------------------------------------------------------------------------------------------
// Modo ao vivo (simulação do firmware de produção)
// ---------------------------------------------------------------------------------------------
struct LiveRec { long win; float rms_db, prob; int pos, votes, alert; };

static int live_main(const char* rawfile, double speed) {
  setvbuf(stdout, nullptr, _IOLBF, 0);
  FILE* f = fopen(rawfile, "rb");
  if (!f) { fprintf(stderr, "nao abriu %s\n", rawfile); return 1; }
  std::vector<int16_t> pcm;
  int16_t tmp[4096];
  size_t n;
  while ((n = fread(tmp, 2, 4096, f)) > 0) pcm.insert(pcm.end(), tmp, tmp + n);
  fclose(f);
  if (pcm.size() < (size_t)DSP_N) { fprintf(stderr, "audio curto\n"); return 1; }
  dsp_init();
  RuntimeParams rp;
  params_defaults(&rp);
#ifdef LIVE_PROB_THRESHOLD   // simula o firmware de produção (override de board_config.h)
  rp.thr = LIVE_PROB_THRESHOLD;
#endif
  DecisionState ds;
  decision_reset(&ds);
  std::vector<LiveRec> ring;
  long alerts = 0, windows = 0, gated = 0, poss = 0;
  std::string inbuf;
  static int16_t win[DSP_N];
  const double step_s = (double)DSP_HOP / DSP_FS / speed;      // tempo de parede por janela
  const auto t0 = clk::now();
  auto next_tick = t0;
  const auto tick = std::chrono::duration<double>(0.1 / speed);
  auto next_stats = t0 + std::chrono::duration<double>(5.0 / speed);
  for (long w = 0;; w++) {
    std::this_thread::sleep_until(t0 + std::chrono::duration<double>((w + 2) * step_s));
    for (int i = 0; i < DSP_N; i++) win[i] = pcm[(size_t)((w * DSP_HOP + i) % (long)pcm.size())];
    const int64_t t_ready_us = (int64_t)(w * DSP_HOP + DSP_N) * 1000000LL / DSP_FS;
    Features ft;
    features_compute(win, &ft);
    float prob = -1.0f;
    bool pos = false;
    const bool g = ft.rms_db < rp.gate_db;
    if (!g) {
      float v[MODEL_N_FEATURES];
      features_to_vector(ft, v);
      prob = model_predict(v);
      pos = prob >= rp.thr;
    }
    int64_t first = 0;
    const bool alert = decision_update(&ds, pos, (uint32_t)(t_ready_us / 1000), t_ready_us, false, &first, rp.vote_n, rp.vote_m);
    windows++; gated += g; poss += pos; alerts += alert;
    if (rp.mon) {
      if (ring.size() >= 16) ring.erase(ring.begin());       // igual ao anel do firmware: descarta a mais antiga
      ring.push_back(LiveRec{w, ft.rms_db, prob, pos ? 1 : 0, decision_votes(&ds, rp.vote_m), alert ? 1 : 0});
    }
    if (alert) printf("A,live,%ld,%lld,%lld\n", w, (long long)t_ready_us, (long long)(t_ready_us - first));

    if (clk::now() >= next_tick) {                             // "tarefa T4": comandos + monitor + stats
      next_tick += std::chrono::duration_cast<clk::duration>(tick);
      pollfd pf{0, POLLIN, 0};
      bool want_stats = false;
      while (poll(&pf, 1, 0) > 0 && (pf.revents & POLLIN)) {
        char b[256];
        const ssize_t r = read(0, b, sizeof b);
        if (r <= 0) return 0;                                  // stdin fechou: encerra
        inbuf.append(b, (size_t)r);
      }
      size_t nl;
      while ((nl = inbuf.find('\n')) != std::string::npos) {
        std::string line = inbuf.substr(0, nl);
        inbuf.erase(0, nl + 1);
        char reply[96];
        const CmdKind k = cmd_execute(line.c_str(), &rp, reply, sizeof reply);
        if (k == CMD_STATS) want_stats = true;
        if (reply[0]) printf("%s\n", reply);
      }
      for (const LiveRec& r : ring)
        if (rp.mon) printf("M,%ld,%.1f,%.3f,%d,%d,%d\n", r.win, r.rms_db, r.prob, r.pos, r.votes, r.alert);
      ring.clear();
      if (want_stats || clk::now() >= next_stats) {
        next_stats = clk::now() + std::chrono::duration_cast<clk::duration>(std::chrono::duration<double>(5.0 / speed));
        printf("# live(simulado) win=%ld pos=%ld gated=%ld alerts=%ld\n", windows, poss, gated, alerts);
        printf("P,%.1f,%.3f,%d,%d,%d\n", rp.gate_db, rp.thr, rp.vote_n, rp.vote_m, rp.mon ? 1 : 0);
        printf("S,0,0,0,-1,-1,-1,-1\n");
      }
    }
  }
}

int main(int argc, char** argv) {
  if (argc >= 3 && strcmp(argv[1], "--live") == 0) return live_main(argv[2], argc >= 4 ? atof(argv[3]) : 1.0);
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
      const bool alert = decision_update(&ds, pos, (uint32_t)(t_ready_us / 1000), t_ready_us, false, &first, DSP_VOTE_N, DSP_VOTE_M);
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
