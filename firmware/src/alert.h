// Alerta: LED (obrigatório) e buzzer (opcional). Só T3 chama estas funções.
#pragma once
#include <stdint.h>

void alert_init();
// Aciona o alerta: LED por DSP_LED_ON_MS e, se USE_BUZZER, buzzer por BUZZER_ON_MS.
void alert_trigger(uint32_t now_ms);
// Apaga LED/buzzer quando vencem. Chamar periodicamente (T3 acorda por timeout da fila).
void alert_update(uint32_t now_ms);
// true enquanto o buzzer toca e por DSP_BUZZER_TAIL_MS depois: a detecção ignora as janelas
// (evita realimentação buzzer -> microfone).
bool alert_suppressed(uint32_t now_ms);
