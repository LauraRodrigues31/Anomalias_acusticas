// Inferência do modelo (regressão logística com padronização). Pesos vêm de model_params.h,
// gerado a partir do treino (ml/train.py → ml/gen_headers.py).
#pragma once

// z = Σ w_i·(x_i − mean_i)/std_i + b ;  p = 1/(1+exp(−z))
float model_predict(const float* x);
