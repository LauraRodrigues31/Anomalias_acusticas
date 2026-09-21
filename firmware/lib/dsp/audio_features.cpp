#include "audio_features.h"
#include "fft.h"
#include <math.h>

static float s_x[DSP_N];
static float s_mag[DSP_NBINS];

void features_compute(const int16_t* s, Features* out) {
  // 1-2) escala para [-1,1) e remove DC (o INMP441 tem offset)
  float sum = 0.0f;
  for (int n = 0; n < DSP_N; n++) {
    s_x[n] = (float)s[n] * (1.0f / 32768.0f);
    sum += s_x[n];
  }
  const float mean = sum / DSP_N;
  float e = 0.0f;
  for (int n = 0; n < DSP_N; n++) {
    s_x[n] -= mean;
    e += s_x[n] * s_x[n];
  }
  // 3) RMS antes da janela de Hann
  out->rms_db = 20.0f * log10f(sqrtf(e / DSP_N) + 1e-9f);

  // 4-5) Hann + FFT
  const float* w = dsp_hann();
  for (int n = 0; n < DSP_N; n++) s_x[n] *= w[n];
  fft_real_mag(s_x, s_mag);

  // 6) estatísticas espectrais em k = 1..N/2
  float sm = 0.0f, sfm = 0.0f, total = 0.0f, band = 0.0f, pmax = 0.0f, magmax = -1.0f;
  int kpk = 1;
  for (int k = 1; k < DSP_NBINS; k++) {
    const float m = s_mag[k], p = m * m;
    sm += m;
    sfm += (float)k * m;
    total += p;
    if (k >= DSP_BAND_K_LO && k <= DSP_BAND_K_HI) {
      band += p;
      if (p > pmax) pmax = p;
    }
    if (m > magmax) {
      magmax = m;
      kpk = k;
    }
  }
  out->centroid_norm = (sfm * DSP_DF / (sm + 1e-12f)) / DSP_NYQ;
  out->band_ratio = band / (total + 1e-12f);
  out->band_peakiness = pmax / (band + 1e-12f);
  out->peak_freq_norm = ((float)kpk * DSP_DF) / DSP_NYQ;
}

void features_to_vector(const Features& f, float* v) {
  v[0] = f.centroid_norm;
  v[1] = f.band_ratio;
  v[2] = f.band_peakiness;
  v[3] = f.peak_freq_norm;
}
