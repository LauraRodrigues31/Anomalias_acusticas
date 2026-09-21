#include "ring.h"
#include <string.h>

void ring_init(Ring* r) {
  memset(r->data, 0, sizeof r->data);
  for (int i = 0; i < RING_BLOCKS; i++) {
    r->t_ready_us[i] = 0;
    r->meta[i] = BlockMeta{0, 0};
    r->seq[i].store(0);
  }
  r->wr_id.store(0);
}

void ring_write(Ring* r, uint32_t id, const int16_t* blk, const BlockMeta& m, int64_t t_ready_us) {
  const int slot = id % RING_BLOCKS;
  r->seq[slot].store(0, std::memory_order_release);        // slot "em escrita"
  memcpy(r->data[slot], blk, sizeof(int16_t) * DSP_HOP);
  r->meta[slot] = m;
  r->t_ready_us[slot] = t_ready_us;
  r->seq[slot].store(id, std::memory_order_release);       // publica dados + metadados
  r->wr_id.store(id, std::memory_order_release);
}

bool ring_read(Ring* r, uint32_t* rd_id, int16_t* out, BlockMeta* m, int64_t* t_ready_us, uint32_t* lost) {
  *lost = 0;
  const uint32_t newest = r->wr_id.load(std::memory_order_acquire);
  // Bloco `*rd_id` já foi sobrescrito (T1 avançou RING_BLOCKS ou mais): pula para o mais
  // antigo ainda válido, que é newest - (RING_BLOCKS - 1).
  if (*rd_id + RING_BLOCKS <= newest) {
    const uint32_t oldest_valid = newest - (RING_BLOCKS - 1);
    *lost = oldest_valid - *rd_id;
    *rd_id = oldest_valid;
  }
  const int slot = *rd_id % RING_BLOCKS;
  bool ok = r->seq[slot].load(std::memory_order_acquire) == *rd_id;
  if (ok) {
    memcpy(out, r->data[slot], sizeof(int16_t) * DSP_HOP);
    *m = r->meta[slot];
    *t_ready_us = r->t_ready_us[slot];
    // Conferência final: se T1 sobrescreveu durante a cópia, o dado está rasgado.
    ok = r->seq[slot].load(std::memory_order_acquire) == *rd_id;
  }
  (*rd_id)++;
  if (!ok) (*lost)++;
  return ok;
}
