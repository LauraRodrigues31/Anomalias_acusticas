#include "model.h"
#include "model_params.h"
#include <math.h>

float model_predict(const float* x) {
  float z = MODEL_B;
  for (int i = 0; i < MODEL_N_FEATURES; i++) z += MODEL_W[i] * (x[i] - MODEL_MEAN[i]) / MODEL_STD[i];
  return 1.0f / (1.0f + expf(-z));
}
