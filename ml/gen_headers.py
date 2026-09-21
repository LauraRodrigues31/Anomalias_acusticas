"""Gera firmware/include/dsp_config.h e model_params.h a partir de ml/config.py e
models/model_params.json (se existir; senão usa parâmetros PROVISÓRIOS)."""
import json
import os
from ml import config as C

INC = os.path.join(C.ROOT, "firmware", "include")
PARAMS = os.path.join(C.ROOT, "models", "model_params.json")

# Detector provisório (Fase 1-3): heurística logística sobre band_ratio e band_peakiness.
PROVISIONAL = dict(provisional=True, mean=[0, 0, 0, 0], std=[1, 1, 1, 1],
                   w=[0.0, 12.0, 6.0, 0.0], b=-9.0, prob_threshold=0.5,
                   feature_names=C.FEATURE_NAMES)


def fl(x):
    """Literal float C++ válido (garante '.' ou expoente antes do 'f')."""
    t = f"{float(x):.9g}"
    return t + ("" if any(c in t for c in ".eEn") else ".0") + "f"


def arr(name, v):
    return f"static const float {name}[] = {{ " + ", ".join(fl(x) for x in v) + " };\n"


def main():
    with open(os.path.join(INC, "dsp_config.h"), "w") as f:
        f.write(f"""// GERADO por ml/gen_headers.py a partir de ml/config.py — NÃO edite à mão.
#pragma once
#define DSP_FS {C.FS}
#define DSP_N {C.N}
#define DSP_HOP {C.HOP}
#define DSP_NBINS {C.NBINS}
#define DSP_DF ({C.FS}.0f / {C.N}.0f)
#define DSP_NYQ {C.NYQ:.1f}f
#define DSP_BAND_K_LO {C.BAND_K_LO}
#define DSP_BAND_K_HI {C.BAND_K_HI}
#define DSP_RMS_GATE_DB {C.RMS_GATE_DB:.1f}f
#define DSP_VOTE_N {C.VOTE_N}
#define DSP_VOTE_M {C.VOTE_M}
#define DSP_COOLDOWN_MS {C.COOLDOWN_MS}
#define DSP_LED_ON_MS {C.LED_ON_MS}
#define DSP_BUZZER_TAIL_MS {C.BUZZER_SUPPRESS_TAIL_MS}
""")
    p = json.load(open(PARAMS)) if os.path.exists(PARAMS) else PROVISIONAL
    with open(os.path.join(INC, "model_params.h"), "w") as f:
        f.write("// GERADO por ml/gen_headers.py — NÃO edite à mão.\n#pragma once\n")
        if p.get("provisional"):
            f.write("#define MODEL_PROVISIONAL 1  // detector provisório, não é o modelo treinado\n")
        f.write(f"#define MODEL_N_FEATURES {len(p['w'])}\n")
        f.write(arr("MODEL_MEAN", p["mean"]))
        f.write(arr("MODEL_STD", p["std"]))
        f.write(arr("MODEL_W", p["w"]))
        f.write(f"static const float MODEL_B = {fl(p['b'])};\n")
        f.write(f"#define PROB_THRESHOLD {fl(p['prob_threshold'])}\n")
    print("headers gerados (%s)" % ("PROVISÓRIO" if p.get("provisional") else "modelo treinado"))


if __name__ == "__main__":
    main()
