// Arquitetura RTOS: 4 tarefas, buffer circular, semáforo de contagem, fila e 2 mutexes.
// Diagrama: docs/diagrama_tarefas.svg
#pragma once
#include <stdint.h>
#include "board_config.h"

// Mensagem T2 -> T3 (copiada pela fila; sem ponteiros para memória compartilhada).
enum : uint8_t {
  FM_CLIP_START = 1,  // modo teste: T3 zera a decisão
  FM_CLIP_END = 2,    // modo teste: T3 responde DONE após processar
  FM_NOWINDOW = 4     // mensagem só de controle (não há features)
};

struct FeatureMsg {
  uint32_t window_id;
  uint32_t clip_id;
  uint8_t flags;
  int64_t t_block_ready_us;  // T1: bloco (que completa a janela) pronto
  int64_t t_feat_start_us;   // T2: início do cálculo
  int64_t t_feat_done_us;    // T2: fim do cálculo (entrada na fila)
  float rms_db;
  float feat[4];             // [centroid_norm, band_ratio, band_peakiness, peak_freq_norm]
};

// Cria objetos de sincronização e tarefas (chamar uma vez no setup; toda alocação ocorre aqui).
void rtos_start();
