// Buffer circular de blocos: produtor ÚNICO (T1) e consumidor ÚNICO (T2).
//
// Por que funciona sem mutex: cada índice tem um só dono (T1 escreve wr_id; T2 lê e mantém
// rd_id). O semáforo de contagem `blocks_ready` dá a ordem "dado publicado -> consumidor
// acorda". O único caso perigoso é o OVERRUN (T2 atrasada 8 blocos): T1 sobrescreve o bloco
// mais antigo. Para que isso seja "controlado" cada slot tem um número de sequência (estilo
// seqlock): T1 marca o slot como ocupado (0), grava e publica o id; T2 confere o id antes e
// depois de copiar e, se mudou, descarta a leitura e ressincroniza (nunca usa dado rasgado).
#pragma once
#include <stdint.h>
#include <atomic>
#include "board_config.h"
#include "audio_capture.h"

struct Ring {
  int16_t data[RING_BLOCKS][DSP_HOP];
  int64_t t_ready_us[RING_BLOCKS];
  BlockMeta meta[RING_BLOCKS];
  std::atomic<uint32_t> seq[RING_BLOCKS];  // id publicado no slot (0 = ocupado/vazio)
  std::atomic<uint32_t> wr_id;             // id do último bloco publicado (1, 2, 3, ...)
};

void ring_init(Ring* r);

// Chamado só por T1: grava o bloco `id` (id = 1, 2, ...) e publica.
void ring_write(Ring* r, uint32_t id, const int16_t* blk, const BlockMeta& m, int64_t t_ready_us);

// Chamado só por T2. `*rd_id` é o próximo id a ler; é ajustado (e avançado) aqui.
// Retorna true se `out` contém o bloco lido com integridade. `*lost` = nº de blocos perdidos
// antes/durante esta leitura (> 0 => descontinuidade: o chamador descarta o bloco anterior
// da janela). Retorna false se o bloco foi perdido/rasgado (`out` inválido).
bool ring_read(Ring* r, uint32_t* rd_id, int16_t* out, BlockMeta* m, int64_t* t_ready_us, uint32_t* lost);
