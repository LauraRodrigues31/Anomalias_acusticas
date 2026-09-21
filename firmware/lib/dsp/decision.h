// Decisão N de M + cooldown (seção 6 do CLAUDE.md). Portátil, sem relógio próprio:
// o chamador passa o tempo atual. Espelhada em ml/decision.py.
#pragma once
#include <stdint.h>
#include "dsp_config.h"

struct DecisionState {
  uint8_t pos[DSP_VOTE_M];         // últimas M janelas (0/1), buffer circular
  int64_t t_us[DSP_VOTE_M];        // instante de cada janela (µs), p/ medir t_decision
  int head;                        // próxima posição de escrita
  int count;                       // quantas janelas válidas (<= M)
  bool has_alerted;
  uint32_t last_alert_ms;          // início do cooldown
};

void decision_reset(DecisionState* s);

// Registra uma janela. `pos`: janela positiva; `now_ms`: instante; `t_us`: instante em µs
// (para t_decision); `suppressed`: buzzer tocando (janela ignorada por completo).
// Retorna true se deve ALERTAR; nesse caso *first_pos_us recebe o instante da 1ª janela
// positiva do voto vencedor.
bool decision_update(DecisionState* s, bool pos, uint32_t now_ms, int64_t t_us, bool suppressed,
                     int64_t* first_pos_us);
