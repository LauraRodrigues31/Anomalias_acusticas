// Extração de features por janela (contrato: docs/feature_spec.md). Portátil.
#pragma once
#include <stdint.h>
#include "dsp_config.h"

struct Features {
  float rms_db;
  float centroid_norm;
  float band_ratio;
  float band_peakiness;
  float peak_freq_norm;
};

// Entrada: DSP_N amostras int16. Não reentrante (buffers estáticos); só T2 chama.
void features_compute(const int16_t* s, Features* out);

// Vetor de entrada do modelo, ordem fixa: [centroid, band_ratio, peakiness, peak_freq].
void features_to_vector(const Features& f, float* v);
