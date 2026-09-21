// Fonte de áudio: I2S (INMP441) ou serial (modo de teste). T1 é o único chamador.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include "board_config.h"

enum : uint8_t { BLK_CLIP_START = 1, BLK_CLIP_END = 2 };  // usados só no modo serial

struct BlockMeta {
  uint32_t clip_id;
  uint8_t flags;
};

bool audio_init();

// Bloqueia até haver DSP_HOP amostras int16. Nunca imprime na serial.
bool audio_read_block(int16_t* out, BlockMeta* meta);

// Conversão 24-bit-em-32 -> int16 com deslocamento configurável e saturação.
int16_t audio_convert_sample(int32_t raw);

#if !AUDIO_SOURCE_SERIAL
// Para o autoteste: leitura bruta de n palavras de 32 bits. Retorna n lidas.
size_t audio_i2s_read_raw(int32_t* buf, size_t n);
#endif
