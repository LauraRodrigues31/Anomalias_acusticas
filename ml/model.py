"""Inferência do modelo em numpy (espelha firmware/lib/dsp/model.cpp)."""
import json
import os
import numpy as np
from ml import config as C

PARAMS_JSON = os.path.join(C.ROOT, "models", "model_params.json")


def load_params(path=PARAMS_JSON):
    with open(path) as f:
        return json.load(f)


def predict(params, X):
    """X: (n, n_features). Regressão logística com padronização."""
    X = np.asarray(X, dtype=np.float32)
    mean = np.asarray(params["mean"], dtype=np.float32)
    std = np.asarray(params["std"], dtype=np.float32)
    w = np.asarray(params["w"], dtype=np.float32)
    z = ((X - mean) / std) @ w + np.float32(params["b"])
    return 1.0 / (1.0 + np.exp(-z))
