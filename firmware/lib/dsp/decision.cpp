#include "decision.h"

void decision_reset(DecisionState* s) {
  for (int i = 0; i < DSP_VOTE_M; i++) {
    s->pos[i] = 0;
    s->t_us[i] = 0;
  }
  s->head = 0;
  s->count = 0;
  s->has_alerted = false;
  s->last_alert_ms = 0;
}

bool decision_update(DecisionState* s, bool pos, uint32_t now_ms, int64_t t_us, bool suppressed,
                     int64_t* first_pos_us) {
  if (suppressed) return false;  // durante o toque do buzzer as janelas são ignoradas
  s->pos[s->head] = pos ? 1 : 0;
  s->t_us[s->head] = t_us;
  s->head = (s->head + 1) % DSP_VOTE_M;
  if (s->count < DSP_VOTE_M) s->count++;

  int npos = 0;
  for (int i = 0; i < s->count; i++) npos += s->pos[i];
  // (uint32 - uint32) é seguro contra a virada do contador de ms
  const bool cool_ok = !s->has_alerted || (uint32_t)(now_ms - s->last_alert_ms) >= (uint32_t)DSP_COOLDOWN_MS;
  if (npos >= DSP_VOTE_N && cool_ok) {
    s->has_alerted = true;
    s->last_alert_ms = now_ms;
    if (first_pos_us) {
      // varre do mais antigo ao mais novo
      int idx = (s->head - s->count + DSP_VOTE_M) % DSP_VOTE_M;
      for (int i = 0; i < s->count; i++, idx = (idx + 1) % DSP_VOTE_M)
        if (s->pos[idx]) {
          *first_pos_us = s->t_us[idx];
          break;
        }
    }
    return true;
  }
  return false;
}
