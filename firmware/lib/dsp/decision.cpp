#include "decision.h"

void decision_reset(DecisionState* s) {
  for (int i = 0; i < DECISION_MAX_M; i++) {
    s->pos[i] = 0;
    s->t_us[i] = 0;
  }
  s->head = 0;
  s->count = 0;
  s->has_alerted = false;
  s->last_alert_ms = 0;
}

static int clamp_m(int m) { return m < 1 ? 1 : (m > DECISION_MAX_M ? DECISION_MAX_M : m); }

int decision_votes(const DecisionState* s, int m) {
  m = clamp_m(m);
  const int k = s->count < m ? s->count : m;
  int npos = 0;
  for (int i = 0; i < k; i++) npos += s->pos[(s->head - 1 - i + 2 * DECISION_MAX_M) % DECISION_MAX_M];
  return npos;
}

bool decision_update(DecisionState* s, bool pos, uint32_t now_ms, int64_t t_us, bool suppressed,
                     int64_t* first_pos_us, int n, int m) {
  if (suppressed) return false;  // durante o toque do buzzer as janelas são ignoradas
  m = clamp_m(m);
  if (n < 1) n = 1;
  if (n > m) n = m;
  s->pos[s->head] = pos ? 1 : 0;
  s->t_us[s->head] = t_us;
  s->head = (s->head + 1) % DECISION_MAX_M;
  if (s->count < DECISION_MAX_M) s->count++;

  const int npos = decision_votes(s, m);
  // (uint32 - uint32) é seguro contra a virada do contador de ms
  const bool cool_ok = !s->has_alerted || (uint32_t)(now_ms - s->last_alert_ms) >= (uint32_t)DSP_COOLDOWN_MS;
  if (npos >= n && cool_ok) {
    s->has_alerted = true;
    s->last_alert_ms = now_ms;
    if (first_pos_us) {
      const int k = s->count < m ? s->count : m;
      // varre do mais antigo ao mais novo das últimas k janelas
      for (int i = k - 1; i >= 0; i--) {
        const int idx = (s->head - 1 - i + 2 * DECISION_MAX_M) % DECISION_MAX_M;
        if (s->pos[idx]) {
          *first_pos_us = s->t_us[idx];
          break;
        }
      }
    }
    return true;
  }
  return false;
}
