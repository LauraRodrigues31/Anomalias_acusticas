#include "fft.h"
#include <math.h>

// Buffers e tabelas estáticos: nenhuma alocação dinâmica e nada grande na pilha da tarefa.
static float s_re[DSP_N], s_im[DSP_N];
static float s_cos[DSP_N / 2], s_sin[DSP_N / 2];
static float s_hann[DSP_N];
static unsigned short s_rev[DSP_N];
static bool s_ready = false;

void dsp_init() {
  if (s_ready) return;
  const double two_pi = 6.283185307179586476925286766559;
  for (int i = 0; i < DSP_N / 2; i++) {
    s_cos[i] = (float)cos(two_pi * i / DSP_N);
    s_sin[i] = (float)-sin(two_pi * i / DSP_N);  // e^{-j2πi/N}
  }
  for (int n = 0; n < DSP_N; n++) s_hann[n] = (float)(0.5 - 0.5 * cos(two_pi * n / DSP_N));
  int bits = 0;
  while ((1 << bits) < DSP_N) bits++;
  for (int i = 0; i < DSP_N; i++) {
    int r = 0;
    for (int b = 0; b < bits; b++)
      if (i & (1 << b)) r |= 1 << (bits - 1 - b);
    s_rev[i] = (unsigned short)r;
  }
  s_ready = true;
}

const float* dsp_hann() { return s_hann; }

void fft_real_mag(const float* x, float* mag) {
  for (int i = 0; i < DSP_N; i++) {
    s_re[s_rev[i]] = x[i];
    s_im[s_rev[i]] = 0.0f;
  }
  for (int len = 2; len <= DSP_N; len <<= 1) {
    const int half = len >> 1, step = DSP_N / len;
    for (int i = 0; i < DSP_N; i += len) {
      for (int j = 0, t = 0; j < half; j++, t += step) {
        const float wr = s_cos[t], wi = s_sin[t];
        const int a = i + j, b = a + half;
        const float tr = s_re[b] * wr - s_im[b] * wi;
        const float ti = s_re[b] * wi + s_im[b] * wr;
        s_re[b] = s_re[a] - tr;
        s_im[b] = s_im[a] - ti;
        s_re[a] += tr;
        s_im[a] += ti;
      }
    }
  }
  for (int k = 0; k <= DSP_N / 2; k++) mag[k] = sqrtf(s_re[k] * s_re[k] + s_im[k] * s_im[k]);
}
