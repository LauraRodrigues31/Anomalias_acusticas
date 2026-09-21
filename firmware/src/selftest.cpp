#include "board_config.h"
#if BOARD_SELFTEST
#include <Arduino.h>
#include <math.h>
#include "alert.h"
#include "audio_capture.h"
#include "selftest.h"

#define ST_SAMPLES 8000  // 500 ms a 16 kHz

static int32_t raw[ST_SAMPLES];  // estático (32 KB): não cabe na pilha

static void bar(float db) {
  const int W = 40;
  int n = (int)((db + 90.0f) / 90.0f * W);
  if (n < 0) n = 0;
  if (n > W) n = W;
  Serial.print('[');
  for (int i = 0; i < W; i++) Serial.print(i < n ? '#' : '.');
  Serial.print(']');
}

void selftest_run() {
  Serial.println("# === AUTOTESTE DE BRING-UP ===");
  pinMode(LED_PIN, OUTPUT);
  for (int i = 0; i < 3; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(150);
    digitalWrite(LED_PIN, LOW);
    delay(150);
  }
#if USE_BUZZER
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, HIGH);
  delay(200);
  digitalWrite(BUZZER_PIN, LOW);
  Serial.println("# buzzer: 200 ms");
#else
  Serial.println("# buzzer desabilitado (USE_BUZZER=0)");
#endif
  if (!audio_init()) {
    Serial.println("# ERRO: i2s_driver_install/i2s_set_pin falhou");
    for (;;) delay(1000);
  }
  Serial.printf("# I2S ok. SHIFT=%d SWAP=%d BCLK=%d WS=%d DIN=%d\n", I2S_SAMPLE_SHIFT, I2S_CHANNEL_SWAP, I2S_BCLK_PIN,
                I2S_WS_PIN, I2S_DIN_PIN);
  for (;;) {
    if (audio_i2s_read_raw(raw, ST_SAMPLES) != ST_SAMPLES) {
      Serial.println("# ERRO: leitura I2S incompleta");
      continue;
    }
    int32_t rmin = INT32_MAX, rmax = INT32_MIN;
    double rsum = 0, s16sum = 0;
    static int16_t dummy;
    (void)dummy;
    for (int i = 0; i < ST_SAMPLES; i++) {
      if (raw[i] < rmin) rmin = raw[i];
      if (raw[i] > rmax) rmax = raw[i];
      rsum += raw[i];
      s16sum += audio_convert_sample(raw[i]);
    }
    const double dc = s16sum / ST_SAMPLES;
    double e = 0;
    for (int i = 0; i < ST_SAMPLES; i++) {
      double v = audio_convert_sample(raw[i]) - dc;
      e += v * v;
    }
    const float rms = (float)sqrt(e / ST_SAMPLES) / 32768.0f;
    const float db = 20.0f * log10f(rms + 1e-9f);
    Serial.printf("raw min=%ld max=%ld media=%.0f | int16 dc=%.1f rms=%.1f dBFS ", (long)rmin, (long)rmax,
                  rsum / ST_SAMPLES, dc, db);
    bar(db);
    if (rmin == 0 && rmax == 0) Serial.print("  << TRAVADO EM ZERO: confira fiacao/SD/canal (I2S_CHANNEL_SWAP)");
    else if ((rmax >> I2S_SAMPLE_SHIFT) >= 32767 || (rmin >> I2S_SAMPLE_SHIFT) <= -32768) Serial.print("  << SATURANDO");
    else if (db > -20.0f && (rmax - rmin) > 0 && db > -6.0f) Serial.print("  << ruido enorme: fiacao/GND?");
    Serial.println();
    digitalWrite(LED_PIN, db > DSP_RMS_GATE_DB ? HIGH : LOW);  // LED acende acima do gate
  }
}
#endif
