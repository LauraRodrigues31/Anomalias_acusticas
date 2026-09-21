// FFT real de N = DSP_N pontos, radix-2 iterativa, float. Sem dependências de Arduino/FreeRTOS.
#pragma once
#include "dsp_config.h"

// Pré-calcula tabelas (twiddle e Hann periódica). Idempotente. Chamar uma vez na inicialização.
void dsp_init();

// Janela de Hann periódica pré-calculada (N valores).
const float* dsp_hann();

// Calcula |X[k]|, k = 0..N/2, de x[N] (entrada real, já janelada). Usa buffers estáticos
// internos: NÃO é reentrante (só uma tarefa — T2 — chama).
void fft_real_mag(const float* x, float* mag);
