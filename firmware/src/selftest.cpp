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

// Diagnóstico automático: imprime "<<" + causa provável quando a leitura tem um padrão de erro típico.
static void diagnose(int32_t rmin, int32_t rmax, float db, double dc, int n_clip, int n_zero) {
  bool any = false;
  auto say = [&](const char* msg) {
    Serial.print("\n  << ");
    Serial.print(msg);
    any = true;
  };
  // "morto": raw so em 0 e 1 (rms ~ -180 dBFS). Isso NAO e silencio: o INMP441 real em silencio ainda
  // tem ruido de varios LSBs; aqui o microfone simplesmente nao esta entregando dados.
  const bool dead = (rmin >= 0 && rmax <= 1);
  if (dead) {
    say("MICROFONE NAO ESTA ENTREGANDO DADOS (raw so 0/1, rms -180 dBFS; isto NAO e silencio). Causas: "
        "VDD (precisa 3V3), GND, SCK/BCLK (GPIO26), WS/LRCL (GPIO25), SD/DOUT (GPIO33), pino L/R (no GND = canal esquerdo) "
        "e canal (tente I2S_CHANNEL_SWAP 0<->1)");
  } else if (rmin == rmax) {
    say("AMOSTRAS CONSTANTES (!= 0): SD preso em nivel fixo ou sem clock; verifique SD e SCK/WS e o contato dos fios");
  } else if (n_zero > (ST_SAMPLES * 9) / 10) {
    say("mais de 90% das amostras = 0: microfone quase sem sinal; canal errado? tente I2S_CHANNEL_SWAP (0<->1)");
  }
  if (n_clip > ST_SAMPLES / 1000) {
    say("SINAL SATURADO (>0,1% das amostras no limite): aumente I2S_SAMPLE_SHIFT (+1 = -6 dB) ou afaste a fonte");
  }
  if (!dead && rmin != rmax && db < -80.0f) {
    say("nivel muito baixo (< -80 dBFS): normal em silencio total; se uma palma nao passar de -50 dBFS, diminua "
        "I2S_SAMPLE_SHIFT (-1 = +6 dB) e confira o canal");
  }
  if (dc > 3000.0 || dc < -3000.0) {
    say("DC alto (|dc| > 3000): comum no INMP441 e o firmware remove o DC por janela; se vier junto de ruido "
        "alto, suspeite de fiacao/GND");
  }
  if (db > -10.0f && n_clip <= ST_SAMPLES / 1000) {
    say("nivel muito alto (> -10 dBFS): em silencio indica ruido de fiacao (fios longos, GND ruim, 5V no VDD?)");
  }
  if (!any) Serial.print("  (ok)");
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
  Serial.printf("# I2S ok. SHIFT=%d SWAP=%d BCLK=%d WS=%d DIN=%d gate=%.0f dBFS\n", I2S_SAMPLE_SHIFT, I2S_CHANNEL_SWAP,
                I2S_BCLK_PIN, I2S_WS_PIN, I2S_DIN_PIN, (double)DSP_RMS_GATE_DB);
  Serial.println("# (o 1o bloco e descartado: o INMP441 leva ~250 ms para ligar e entrega zeros)");
  audio_i2s_read_raw(raw, ST_SAMPLES);
  for (;;) {
    if (audio_i2s_read_raw(raw, ST_SAMPLES) != ST_SAMPLES) {
      Serial.println("# ERRO: leitura I2S incompleta");
      continue;
    }
    int32_t rmin = INT32_MAX, rmax = INT32_MIN;
    double rsum = 0, s16sum = 0;
    int n_clip = 0, n_zero = 0, peak = 0;
    for (int i = 0; i < ST_SAMPLES; i++) {
      if (raw[i] < rmin) rmin = raw[i];
      if (raw[i] > rmax) rmax = raw[i];
      if (raw[i] == 0) n_zero++;
      rsum += raw[i];
      const int16_t v = audio_convert_sample(raw[i]);
      s16sum += v;
      const int a = v < 0 ? -(int)v : (int)v;
      if (a > peak) peak = a;
      if (a >= 32700) n_clip++;
    }
    const double dc = s16sum / ST_SAMPLES;
    double e = 0;
    for (int i = 0; i < ST_SAMPLES; i++) {
      double v = audio_convert_sample(raw[i]) - dc;
      e += v * v;
    }
    const float rms = (float)sqrt(e / ST_SAMPLES) / 32768.0f;
    const float db = 20.0f * log10f(rms + 1e-9f);
    Serial.printf("raw min=%ld max=%ld media=%.0f | int16 dc=%.1f pico=%d rms=%.1f dBFS %s ", (long)rmin, (long)rmax,
                  rsum / ST_SAMPLES, dc, peak, db, db >= DSP_RMS_GATE_DB ? "ACIMA-do-gate" : "abaixo-do-gate");
    bar(db);
    diagnose(rmin, rmax, db, dc, n_clip, n_zero);
    Serial.println();
    digitalWrite(LED_PIN, db > DSP_RMS_GATE_DB ? HIGH : LOW);  // LED acende acima do gate
  }
}
#endif
