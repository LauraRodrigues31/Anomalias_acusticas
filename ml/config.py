"""Constantes do projeto (fonte da verdade). Exportadas para o firmware por ml/gen_headers.py.

Não duplique estes valores à mão em outros arquivos.
"""
import os

FS = 16000
N = 1024
HOP = 512
NBINS = N // 2 + 1          # 513 (k = 0..512)
DF = FS / N                 # 15.625 Hz
NYQ = FS / 2                # 8000 Hz (normalização de frequências)

BAND_LO_HZ = 2000.0
BAND_HI_HZ = 4000.0
BAND_K_LO = 128             # 2000 Hz / 15.625
BAND_K_HI = 256             # 4000 Hz / 15.625 (inclusive)

RMS_GATE_DB = -50.0

# Decisão
PROB_THRESHOLD_DEFAULT = 0.5    # sobrescrito por train.py (calibrado na validação)
VOTE_N = 3                      # sobrescritos por models/model_params.json (escolhidos na validação)
VOTE_M = 5
COOLDOWN_MS = 3000
LED_ON_MS = 2000
BUZZER_SUPPRESS_TAIL_MS = 300

FEATURE_NAMES = ["centroid_norm", "band_ratio", "band_peakiness", "peak_freq_norm"]
N_FEATURES = len(FEATURE_NAMES)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Parâmetros de decisão escolhidos no treino (validação) sobrescrevem os padrões acima.
def _load_trained():
    import json
    p = os.path.join(ROOT, "models", "model_params.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


_T = _load_trained()
if _T.get("vote_n") and _T.get("vote_m"):
    VOTE_N, VOTE_M = int(_T["vote_n"]), int(_T["vote_m"])
