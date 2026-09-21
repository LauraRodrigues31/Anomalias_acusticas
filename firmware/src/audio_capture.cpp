#include "audio_capture.h"
#include <Arduino.h>

int16_t audio_convert_sample(int32_t raw) {
  // O INMP441 põe 24 bits nos bits 31..8. Deslocar 16 mantém os 16 mais significativos.
  int32_t v = raw >> I2S_SAMPLE_SHIFT;
  if (v > 32767) v = 32767;      // saturação (só relevante se I2S_SAMPLE_SHIFT < 16)
  if (v < -32768) v = -32768;
  return (int16_t)v;
}

#if !AUDIO_SOURCE_SERIAL
// ---------------------------------------------------------------------------------------------
// Fonte I2S. Arduino-ESP32 2.0.x (ESP-IDF 4.4): driver legado "driver/i2s.h".
// ---------------------------------------------------------------------------------------------
#include "driver/i2s.h"

#define I2S_PORT_NUM I2S_NUM_0

bool audio_init() {
  i2s_config_t cfg = {};
  cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  cfg.sample_rate = DSP_FS;
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  // Quirk conhecido: com ONLY_LEFT alguns cores leem o canal errado; I2S_CHANNEL_SWAP troca.
  cfg.channel_format = I2S_CHANNEL_SWAP ? I2S_CHANNEL_FMT_ONLY_RIGHT : I2S_CHANNEL_FMT_ONLY_LEFT;
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  // DMA: 8 buffers x 256 quadros = 128 ms de folga antes de perder amostras no hardware.
  cfg.dma_buf_count = 8;
  cfg.dma_buf_len = 256;
  cfg.use_apll = false;
  cfg.tx_desc_auto_clear = false;
  cfg.fixed_mclk = 0;
  if (i2s_driver_install(I2S_PORT_NUM, &cfg, 0, nullptr) != ESP_OK) return false;
  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = I2S_BCLK_PIN;
  pins.ws_io_num = I2S_WS_PIN;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num = I2S_DIN_PIN;
  if (i2s_set_pin(I2S_PORT_NUM, &pins) != ESP_OK) return false;
  i2s_zero_dma_buffer(I2S_PORT_NUM);
  return true;
}

size_t audio_i2s_read_raw(int32_t* buf, size_t n) {
  size_t got = 0, total = 0;
  // portMAX_DELAY: a tarefa BLOQUEIA (DMA/ISR acorda) — sem busy-wait.
  while (total < n * sizeof(int32_t)) {
    if (i2s_read(I2S_PORT_NUM, (uint8_t*)buf + total, n * sizeof(int32_t) - total, &got, portMAX_DELAY) != ESP_OK)
      return total / sizeof(int32_t);
    total += got;
  }
  return n;
}

bool audio_read_block(int16_t* out, BlockMeta* meta) {
  static int32_t raw[DSP_HOP];   // estático: fora da pilha de T1
  if (audio_i2s_read_raw(raw, DSP_HOP) != DSP_HOP) return false;
  for (int i = 0; i < DSP_HOP; i++) out[i] = audio_convert_sample(raw[i]);
  meta->clip_id = 0;
  meta->flags = 0;
  return true;
}

#else
// ---------------------------------------------------------------------------------------------
// Fonte serial (modo de teste): "START <clip_id> <n_samples>\n" + n_samples int16 LE.
// O restante do pipeline é idêntico ao do I2S.
// ---------------------------------------------------------------------------------------------
#include <stdlib.h>
#include <stdio.h>

static uint32_t s_clip_id = 0;
static long s_remaining = 0;   // amostras ainda não entregues do clipe atual
static bool s_first = false;

bool audio_init() {
  Serial.setTimeout(200);
  return true;
}

// Lê uma linha terminada em '\n' sem alocar memória. Retorna true se havia linha completa.
static bool read_line(char* buf, size_t cap) {
  static size_t len = 0;
  while (Serial.available() > 0) {
    int c = Serial.read();
    if (c == '\n') {
      buf[len] = 0;
      len = 0;
      return true;
    }
    if (c != '\r' && len + 1 < cap) buf[len++] = (char)c;
  }
  return false;
}

bool audio_read_block(int16_t* out, BlockMeta* meta) {
  static char line[96];
  while (s_remaining <= 0) {
    if (read_line(line, sizeof line)) {
      unsigned id = 0;
      long n = 0;
      if (sscanf(line, "START %u %ld", &id, &n) == 2 && n > 0) {
        s_clip_id = id;
        s_remaining = n;
        s_first = true;
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(2));  // cede a CPU (não é busy-wait)
    }
  }
  const long take = s_remaining < DSP_HOP ? s_remaining : DSP_HOP;
  size_t want = (size_t)take * 2, got = Serial.readBytes((char*)out, want);
  for (size_t i = got / 2; i < DSP_HOP; i++) out[i] = 0;  // completa o bloco com zeros
  s_remaining = (got < want) ? 0 : s_remaining - take;     // timeout: encerra o clipe
  meta->clip_id = s_clip_id;
  meta->flags = (s_first ? BLK_CLIP_START : 0) | (s_remaining <= 0 ? BLK_CLIP_END : 0);
  s_first = false;
  return true;
}
#endif
