#include "alert.h"
#include <Arduino.h>
#include "board_config.h"

static bool s_led_on = false;
static uint32_t s_led_off_ms = 0;
#if USE_BUZZER
static bool s_buz_on = false, s_suppress_valid = false;
static uint32_t s_buz_off_ms = 0, s_suppress_until_ms = 0;
#endif

void alert_init() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
#if USE_BUZZER
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
#endif
}

void alert_trigger(uint32_t now_ms) {
  digitalWrite(LED_PIN, HIGH);
  s_led_on = true;
  s_led_off_ms = now_ms + DSP_LED_ON_MS;
#if USE_BUZZER
  digitalWrite(BUZZER_PIN, HIGH);
  s_buz_on = true;
  s_buz_off_ms = now_ms + BUZZER_ON_MS;
  s_suppress_until_ms = s_buz_off_ms + DSP_BUZZER_TAIL_MS;
  s_suppress_valid = true;
#endif
}

void alert_update(uint32_t now_ms) {
  // (int32_t)(a - b) >= 0 é a comparação segura contra a virada do contador de ms.
  if (s_led_on && (int32_t)(now_ms - s_led_off_ms) >= 0) {
    digitalWrite(LED_PIN, LOW);
    s_led_on = false;
  }
#if USE_BUZZER
  if (s_buz_on && (int32_t)(now_ms - s_buz_off_ms) >= 0) {
    digitalWrite(BUZZER_PIN, LOW);
    s_buz_on = false;
  }
#endif
}

bool alert_suppressed(uint32_t now_ms) {
#if !USE_BUZZER
  (void)now_ms;
  return false;
#else
  if (!s_suppress_valid) return false;
  if ((int32_t)(now_ms - s_suppress_until_ms) >= 0) {
    s_suppress_valid = false;
    return false;
  }
  return true;
#endif
}
