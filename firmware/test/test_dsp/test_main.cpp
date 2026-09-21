// Testes Unity (alvo native): FFT, features e modelo.
#include <cmath>
#include <cstdlib>
#include <unity.h>
#include "fft.h"
#include "audio_features.h"
#include "model.h"
#include "model_params.h"

void setUp() { dsp_init(); }
void tearDown() {}

static void sine(int16_t* s, float hz, float amp) {
  for (int n = 0; n < DSP_N; n++) s[n] = (int16_t)(amp * 32767.0f * sinf(2.0f * (float)M_PI * hz * n / DSP_FS));
}

void test_fft_dc_and_bin() {
  // seno exatamente no bin 64 (1000 Hz): amplitude A => |X[64]| = A*N/2
  float x[DSP_N], mag[DSP_NBINS];
  for (int n = 0; n < DSP_N; n++) x[n] = 0.5f * sinf(2.0f * (float)M_PI * 64 * n / DSP_N);
  fft_real_mag(x, mag);
  TEST_ASSERT_FLOAT_WITHIN(0.5f, 0.5f * DSP_N / 2, mag[64]);
  TEST_ASSERT_TRUE(mag[10] < 1e-2f);
  // impulso => espectro plano
  for (int n = 0; n < DSP_N; n++) x[n] = (n == 0);
  fft_real_mag(x, mag);
  for (int k = 0; k < DSP_NBINS; k += 50) TEST_ASSERT_FLOAT_WITHIN(1e-4f, 1.0f, mag[k]);
}

void test_hann_periodic() {
  const float* w = dsp_hann();
  TEST_ASSERT_FLOAT_WITHIN(1e-6f, 0.0f, w[0]);
  TEST_ASSERT_FLOAT_WITHIN(1e-6f, 1.0f, w[DSP_N / 2]);
}

void test_features_tone_3k() {
  static int16_t s[DSP_N];
  sine(s, 3000.0f, 0.3f);
  Features f;
  features_compute(s, &f);
  TEST_ASSERT_TRUE(f.band_ratio > 0.9f);
  TEST_ASSERT_TRUE(f.band_peakiness > 0.3f);
  TEST_ASSERT_FLOAT_WITHIN(0.02f, 3000.0f / 8000.0f, f.peak_freq_norm);
  TEST_ASSERT_FLOAT_WITHIN(0.02f, 3000.0f / 8000.0f, f.centroid_norm);
  // amplitude 0.3 => rms = 0.3/sqrt2 => -13.5 dBFS
  TEST_ASSERT_FLOAT_WITHIN(0.3f, 20.0f * log10f(0.3f / sqrtf(2.0f)), f.rms_db);
}

void test_features_white_noise() {
  static int16_t s[DSP_N];
  srand(1);
  for (int n = 0; n < DSP_N; n++) s[n] = (int16_t)((rand() % 20001) - 10000);
  Features f;
  features_compute(s, &f);
  TEST_ASSERT_TRUE(f.band_ratio < 0.4f);
  TEST_ASSERT_TRUE(f.band_peakiness < 0.1f);
  TEST_ASSERT_FLOAT_WITHIN(0.06f, 0.5f, f.centroid_norm);
}

void test_features_dc_removed() {
  static int16_t a[DSP_N], b[DSP_N];
  sine(a, 3000.0f, 0.2f);
  for (int n = 0; n < DSP_N; n++) b[n] = a[n] + 3000;  // offset DC
  Features fa, fb;
  features_compute(a, &fa);
  features_compute(b, &fb);
  TEST_ASSERT_FLOAT_WITHIN(0.01f, fa.rms_db, fb.rms_db);
  TEST_ASSERT_FLOAT_WITHIN(1e-3f, fa.band_ratio, fb.band_ratio);
}

void test_silence_gate_level() {
  static int16_t s[DSP_N] = {0};
  Features f;
  features_compute(s, &f);
  TEST_ASSERT_TRUE(f.rms_db < DSP_RMS_GATE_DB);
}

void test_model_range_and_monotonic() {
  float v[MODEL_N_FEATURES] = {0, 0, 0, 0};
  float p0 = model_predict(v);
  TEST_ASSERT_TRUE(p0 >= 0.0f && p0 <= 1.0f);
  // com pesos positivos para band_ratio (provisório), aumentar band_ratio aumenta p
  float v2[MODEL_N_FEATURES] = {0, 1, 1, 0};
  float p1 = model_predict(v2);
  TEST_ASSERT_TRUE(p1 >= p0);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_fft_dc_and_bin);
  RUN_TEST(test_hann_periodic);
  RUN_TEST(test_features_tone_3k);
  RUN_TEST(test_features_white_noise);
  RUN_TEST(test_features_dc_removed);
  RUN_TEST(test_silence_gate_level);
  RUN_TEST(test_model_range_and_monotonic);
  return UNITY_END();
}
