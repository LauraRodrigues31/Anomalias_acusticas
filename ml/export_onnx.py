"""Exporta models/detector.onnx (skl2onnx) a partir de models/detector.joblib e verifica com onnxruntime
que as probabilidades batem com as do scikit-learn (tolerância 1e-5) em janelas reais da validação."""
import os
import joblib
import numpy as np
import onnxruntime as ort
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType
from ml import config as C
from ml import evaluate as E

MODELS = os.path.join(C.ROOT, "models")


def main():
    pipe = joblib.load(os.path.join(MODELS, "detector.joblib"))
    onx = convert_sklearn(pipe, initial_types=[("features", FloatTensorType([None, C.N_FEATURES]))],
                          target_opset=13, options={id(pipe.steps[-1][1]): {"zipmap": False}})
    path = os.path.join(MODELS, "detector.onnx")
    with open(path, "wb") as f:
        f.write(onx.SerializeToString())
    w, _ = E.load_split("val")
    X = w["X"][:20000].astype(np.float32)
    sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    out = sess.run(None, {"features": X})
    p_onnx = out[1][:, 1]                       # saída 1 = probabilidades [P(0), P(1)]
    p_sk = pipe.predict_proba(X)[:, 1]
    err = float(np.abs(p_onnx - p_sk).max())
    print(f"ONNX gravado ({os.path.getsize(path)} bytes). erro máx |onnx - sklearn| = {err:.2e} em {len(X)} janelas")
    assert err < 1e-5, "ONNX diverge do scikit-learn"


if __name__ == "__main__":
    main()
