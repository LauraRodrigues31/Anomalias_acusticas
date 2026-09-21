#include <Arduino.h>
#include "board_config.h"
#include "audio_features.h"
#include "fft.h"
#include "model_params.h"
#include "selftest.h"
#include "tasks.h"

void setup() {
#if AUDIO_SOURCE_SERIAL
  Serial.setRxBufferSize(16384);   // absorve rajadas do host (sem controle de fluxo no USB-serial)
#endif
  Serial.begin(921600);
  delay(200);
  dsp_init();  // tabelas de FFT/Hann (uma vez; sem alocação depois)
#if BOARD_SELFTEST
  selftest_run();
#else
  Serial.println("# Detector de anomalias acusticas (alarme de fumaca)");
#ifdef MODEL_PROVISIONAL
  Serial.println("# ATENCAO: detector PROVISORIO (modelo treinado ainda nao integrado)");
#endif
#if AUDIO_SOURCE_SERIAL
  Serial.println("# modo TESTE: audio injetado pela serial");
#endif
#ifdef LIVE_PROB_THRESHOLD
  Serial.printf("# limiar ao vivo (override calibrado) = %.3f; treino = %.3f\n", (double)LIVE_PROB_THRESHOLD, (double)PROB_THRESHOLD);
#endif
  rtos_start();
  vTaskDelete(NULL);  // o loopTask do Arduino não é mais necessário
#endif
}

void loop() {}
