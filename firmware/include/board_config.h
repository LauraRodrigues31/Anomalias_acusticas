// Configuração da placa e do RTOS (edição manual). Padrões para ESP32 DevKit (esp32dev).
// Constantes de DSP/decisão NÃO ficam aqui: vêm de dsp_config.h (gerado de ml/config.py).
#pragma once
#include "dsp_config.h"

// ---- Pinos (ver docs/HARDWARE_CHECKLIST.md) ----
#ifndef I2S_BCLK_PIN
#define I2S_BCLK_PIN 26          // INMP441 SCK
#endif
#ifndef I2S_WS_PIN
#define I2S_WS_PIN 25            // INMP441 WS (LRCL)
#endif
#ifndef I2S_DIN_PIN
#define I2S_DIN_PIN 33           // INMP441 SD (DOUT)
#endif
#ifndef LED_PIN
#define LED_PIN 2                // LED da placa; LED externo com resistor de 220 ohm
#endif
#ifndef BUZZER_PIN
#define BUZZER_PIN 27
#endif
#ifndef USE_BUZZER
#define USE_BUZZER 0             // buzzer ATIVO (liga/desliga por nível). 0 = desligado
#endif
#ifndef BUZZER_ON_MS
#define BUZZER_ON_MS 500
#endif

// ---- Conversão do INMP441 (24 bits alinhados à esquerda em palavra de 32) ----
#ifndef I2S_SAMPLE_SHIFT
#define I2S_SAMPLE_SHIFT 16      // 32 -> 16 bits; ajuste se o sinal estiver fraco/saturado
#endif
#ifndef I2S_CHANNEL_SWAP
#define I2S_CHANNEL_SWAP 0       // 0 = canal esquerdo, 1 = direito (quirk do driver I2S do ESP32)
#endif

// ---- RTOS ----
#define RING_BLOCKS 8            // blocos de DSP_HOP amostras no buffer circular (~8 KB)
#define FEATURE_Q_DEPTH 8
#define MUTEX_TIMEOUT_MS 50
#define STATS_PERIOD_MS 5000

// Prioridades: maior número = maior prioridade (FreeRTOS).
#define PRIO_T1_CAPTURE 5
#define PRIO_T2_FEATURES 3
#define PRIO_T3_DETECT 2
#define PRIO_T4_MONITOR 1
// Núcleos: captura sozinha no core 0; processamento e monitor no core 1.
#define CORE_T1 0
#define CORE_T2 1
#define CORE_T3 1
#define CORE_T4 1
#define STACK_T1 4096
#define STACK_T2 4096
#define STACK_T3 4096
#define STACK_T4 4096

#ifndef AUDIO_SOURCE_SERIAL
#define AUDIO_SOURCE_SERIAL 0    // 1 = áudio injetado pela serial (esp32-test)
#endif
#ifndef BOARD_SELFTEST
#define BOARD_SELFTEST 0
#endif
