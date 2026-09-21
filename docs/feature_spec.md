# Contrato de features (fonte da verdade)

Python (`ml/features.py`) e C++ (`firmware/lib/dsp/features.cpp`) **devem ser idênticos**.
Qualquer mudança passa primeiro por este arquivo, depois por Python, C++ e `tests/parity_test.py`.

## Constantes (`ml/config.py` → `firmware/include/dsp_config.h` via `ml/gen_headers.py`)

| Nome | Valor |
|---|---|
| `FS` | 16000 Hz |
| `N` | 1024 amostras (64 ms) |
| `HOP` | 512 (32 ms, 50% de sobreposição) |
| `NBINS` | 513 (k = 0..512) |
| `DF` | FS/N = 15,625 Hz |
| Banda | 2000–4000 Hz → bins k = 128..256 (inclusive) |
| `RMS_GATE_DB` | −50,0 dBFS |
| `PROB_THRESHOLD` | calibrado na validação (`model_params.h`) |
| `VOTE_N` / `VOTE_M` | 3 / 5 |
| `COOLDOWN_MS` / `LED_ON_MS` | 3000 / 2000 |

## Cálculo por janela (entrada: 1024 `int16`; tudo em `float32`)

1. `x[n] = s[n] / 32768`
2. Remoção de DC: `x[n] -= mean(x)`
3. `rms = sqrt(mean(x²))` (após remover DC, antes de Hann); `rms_db = 20·log10(rms + 1e-9)`
4. Hann **periódica**: `w[n] = 0.5 − 0.5·cos(2πn/N)`; `xw = x·w`
5. FFT real de `xw`; `mag[k] = |X[k]|` sem normalização, k = 0..512; `f_k = k·DF`
6. Estatísticas espectrais usam k = 1..512 (sem DC):
   - `centroid_hz = Σ f_k·mag_k / (Σ mag_k + 1e-12)`; `centroid_norm = centroid_hz / 8000`
   - `P_k = mag_k²`; `total_power = Σ P_k` (k=1..512); `band_power = Σ P_k` (k=128..256)
   - `band_ratio = band_power / (total_power + 1e-12)`
   - `band_peakiness = max_{k∈[128,256]} P_k / (band_power + 1e-12)`
   - `peak_freq_norm = (argmax_{k=1..512} mag_k · DF) / 8000`

## Vetor do modelo (ordem fixa)

`[centroid_norm, band_ratio, band_peakiness, peak_freq_norm]`

`rms_db` **não** entra no modelo: é usado como *gate* (`rms_db < RMS_GATE_DB` ⇒ janela negativa, modelo não roda) e registrado nos logs.

## Tolerâncias do teste de paridade

`rtol = 1e-3`, `atol = 1e-5` (`centroid_norm`: `atol = 1e-4`). Relaxar só com causa numérica documentada.

## Extras

Nenhuma feature extra foi adicionada até aqui. MFCC fica fora do núcleo.

## Notas numéricas da paridade (float32)

- `band_peakiness` só é comparada quando `band_ratio ≥ 1e-4`. Abaixo disso (ex.: tom puro de 6 kHz) a banda 2–4 kHz contém só vazamento da janela de Hann, cuja amplitude está no piso de ruído do float32 da FFT; o erro relativo chega a ~2e-3 sem qualquer efeito prático (a janela é claramente negativa).
- `rms_db` só é comparada quando `rms_db ≥ −80`. Para sinal constante (DC puro), o Python (soma em pares do numpy) dá exatamente 0 e o C++ (soma ingênua) deixa resíduo de arredondamento (≈ −96 dBFS). Ambos estão muito abaixo do gate (−50 dBFS), portanto a decisão é idêntica.
- Nenhuma feature é comparada em janelas com `rms_db < −80` dBFS (silêncio quase digital, p.ex. −120 dBFS com ruído de 1 LSB): o `argmax` do espectro é decidido por ruído de arredondamento e diverge entre numpy e C++ (observado em `fs_608737.wav`); essas janelas ficam abaixo do gate (−50 dBFS) e nunca chegam ao modelo.
