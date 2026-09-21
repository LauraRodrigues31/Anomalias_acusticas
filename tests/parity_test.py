"""Paridade Python x C++ (seções 4 e 5 do CLAUDE.md).

Features: numpy float32 vs dsp_cli (C++ nativo) nas mesmas janelas.
Modelo: probabilidades numpy (e ONNX, se existir) vs inferência C++.
Sinais: sintéticos + WAVs reais/processados se existirem (--wavs DIR).
Uso: python -m tests.parity_test [--wavs DIR]
"""
import argparse
import glob
import os
import sys
import numpy as np
from ml import config as C
from ml import features as F
from ml import model as M
from ml.gen_headers import PROVISIONAL
from tests.cli_io import run_native

RTOL, ATOL = 1e-3, 1e-5
ATOL_CENT = 1e-4
ATOL_DB = 5e-3      # rms_db é em dB (escala ~ -100..0): tolerância absoluta em dB
MODEL_TOL = 1e-4


def synthetic_signals(rng):
    t = np.arange(4 * C.FS) / C.FS
    sig = {}
    for f0 in (500, 1200, 2800, 3100, 3500, 6000):
        sig[f"tone{f0}"] = 0.3 * np.sin(2 * np.pi * f0 * t)
    sig["white"] = 0.1 * rng.standard_normal(len(t))
    pink = np.cumsum(rng.standard_normal(len(t)))
    brown = pink - np.convolve(pink, np.ones(4000) / 4000, mode="same")   # remove deriva lenta
    sig["brown"] = 0.3 * brown / np.abs(brown).max()
    burst = np.zeros(len(t)); burst[8000:8400] = rng.standard_normal(400) * 0.8
    sig["click"] = burst + 0.005 * rng.standard_normal(len(t))
    beep = 0.25 * np.sin(2 * np.pi * 3100 * t) * (np.sin(2 * np.pi * 2 * t) > 0)
    sig["beeps_noise"] = beep + 0.03 * rng.standard_normal(len(t))
    sig["quiet_dc"] = 0.001 * rng.standard_normal(len(t)) + 0.02
    return {k: np.clip(v * 32768, -32768, 32767).astype(np.int16) for k, v in sig.items()}


def load_wavs(d, limit=30):
    import soundfile as sf
    from scipy.signal import resample_poly
    out = {}
    for p in sorted(glob.glob(os.path.join(d, "**", "*.wav"), recursive=True))[:limit]:
        x, fs = sf.read(p, dtype="float32", always_2d=True)
        x = x.mean(axis=1)
        if fs != C.FS:
            x = resample_poly(x, C.FS, fs).astype(np.float32)
        out[os.path.basename(p)] = np.clip(x * 32767, -32768, 32767).astype(np.int16)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wavs", help="pasta com WAVs reais (opcional)")
    a = ap.parse_args()
    rng = np.random.default_rng(0)
    sigs = synthetic_signals(rng)
    if a.wavs:
        sigs.update(load_wavs(a.wavs))
    res = run_native(list(sigs.items()))

    pfile = M.PARAMS_JSON
    params = M.load_params() if os.path.exists(pfile) else PROVISIONAL
    onnx_sess = None
    onnx_path = os.path.join(C.ROOT, "models", "detector.onnx")
    if os.path.exists(onnx_path) and not params.get("provisional"):
        import onnxruntime as ort
        onnx_sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])

    fails, nwin = [], 0
    worst = {k: 0.0 for k in ["rms_db"] + C.FEATURE_NAMES + ["prob", "prob_onnx"]}
    for cid, x in sigs.items():
        py = F.clip_features(x)
        cw = res[cid]["W"]
        if len(py) != len(cw):
            fails.append(f"{cid}: nº de janelas {len(py)} != {len(cw)}")
            continue
        for i, (d, w) in enumerate(zip(py, cw)):
            nwin += 1
            if d["rms_db"] < -80.0:
                # Silêncio quase digital (ruído de 1 LSB): argmax/centroid são decididos por arredondamento
                # do float32 e a janela nunca chega ao modelo (gate = -50 dBFS). Ver feature_spec.md.
                continue
            for k in C.FEATURE_NAMES:
                # band_peakiness só é numericamente significativa se há energia na banda: com
                # band_ratio < 1e-4 (ex.: tom de 6 kHz) a razão é feita de vazamento da Hann
                # abaixo do piso de ruído do float32 (erro relativo ~1e-3 legítimo). Ver feature_spec.md.
                if k == "band_peakiness" and d["band_ratio"] < 1e-4:
                    continue
                atol = ATOL_CENT if k == "centroid_norm" else ATOL
                err = abs(d[k] - w[k])
                worst[k] = max(worst[k], err)
                if err > atol + RTOL * abs(d[k]):
                    fails.append(f"{cid}[{i}] {k}: py={d[k]:.7g} c={w[k]:.7g}")
            err = abs(d["rms_db"] - w["rms_db"])
            if d["rms_db"] < -80.0:      # piso do float32 (soma ingênua de 1024 termos): irrelevante, gate = -50
                err = 0.0
            worst["rms_db"] = max(worst["rms_db"], err)
            if err > ATOL_DB:
                fails.append(f"{cid}[{i}] rms_db: py={d['rms_db']:.4f} c={w['rms_db']:.4f}")
            # modelo: só nas janelas que passaram no gate do C++ (prob >= 0)
            if w["prob"] >= 0:
                v = F.feature_vector(d)[None]   # entrada do Python (contrato)
                # para isolar o modelo do erro das features, usa as features do C++ como entrada
                vc = np.array([[w[k] for k in C.FEATURE_NAMES]], dtype=np.float32)
                p_py = float(M.predict(params, vc)[0])
                err = abs(p_py - w["prob"]); worst["prob"] = max(worst["prob"], err)
                if err > MODEL_TOL:
                    fails.append(f"{cid}[{i}] prob(numpy): py={p_py:.7g} c={w['prob']:.7g}")
                if onnx_sess is not None:
                    p_on = float(onnx_sess.run(None, {onnx_sess.get_inputs()[0].name: vc})[1][0][1]
                                 if len(onnx_sess.get_outputs()) > 1 else onnx_sess.run(None, {onnx_sess.get_inputs()[0].name: vc})[0][0])
                    err = abs(p_on - w["prob"]); worst["prob_onnx"] = max(worst["prob_onnx"], err)
                    if err > MODEL_TOL:
                        fails.append(f"{cid}[{i}] prob(onnx): onnx={p_on:.7g} c={w['prob']:.7g}")
    # decisão: reexecuta ml.decision.Decider sobre os pos do C++ e compara as janelas de alerta
    from ml.decision import Decider
    for cid in sigs:
        dec, alerts_py = Decider(), []
        for w in res[cid]["W"]:
            t_ms = int(w["t_block_ready_us"]) // 1000
            if dec.update(bool(w["pos"]), t_ms)[0]:
                alerts_py.append(int(w["win"]))
        alerts_c = [a["win"] for a in res[cid]["A"]]
        if alerts_py != alerts_c:
            fails.append(f"{cid}: decisão py={alerts_py} c={alerts_c}")
    print(f"sinais: {len(sigs)}  janelas comparadas: {nwin}  modelo: "
          f"{'PROVISÓRIO' if params.get('provisional') else 'treinado'}  onnx: {'sim' if onnx_sess else 'não'}")
    print("maior erro absoluto por campo:", {k: f"{v:.2e}" for k, v in worst.items()})
    if fails:
        print(f"FALHOU ({len(fails)}):")
        print("\n".join(fails[:20]))
        return 1
    print("PARIDADE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
