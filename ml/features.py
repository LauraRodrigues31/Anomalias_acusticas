"""Referência Python das features (contrato em docs/feature_spec.md). Tudo em float32."""
import numpy as np
from ml import config as C

_HANN = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(C.N) / C.N)).astype(np.float32)
_K = np.arange(C.NBINS, dtype=np.float32)


def window_features(s):
    """s: 1024 amostras (int16 ou float já em escala int16). Retorna dict de floats.

    Chaves: rms_db, centroid_norm, band_ratio, band_peakiness, peak_freq_norm, band_power.
    """
    x = np.asarray(s, dtype=np.float32) / np.float32(32768.0)
    x = x - x.mean(dtype=np.float32)
    rms = np.sqrt(np.mean(x * x, dtype=np.float32))
    rms_db = 20.0 * np.log10(rms + 1e-9)
    xw = x * _HANN
    mag = np.abs(np.fft.rfft(xw)).astype(np.float32)
    m = mag[1:]
    f = (_K[1:] * np.float32(C.DF)).astype(np.float32)
    centroid_hz = np.sum(f * m, dtype=np.float32) / (np.sum(m, dtype=np.float32) + np.float32(1e-12))
    p = m * m
    total = np.sum(p, dtype=np.float32)
    band = p[C.BAND_K_LO - 1:C.BAND_K_HI]           # índices deslocados de 1 (k=1..512)
    band_power = np.sum(band, dtype=np.float32)
    ratio = band_power / (total + np.float32(1e-12))
    peaky = np.max(band) / (band_power + np.float32(1e-12))
    pk = (int(np.argmax(m)) + 1) * C.DF / C.NYQ
    return dict(rms_db=float(rms_db), centroid_norm=float(centroid_hz / C.NYQ),
                band_ratio=float(ratio), band_peakiness=float(peaky),
                peak_freq_norm=float(pk), band_power=float(band_power))


def feature_vector(d):
    return np.array([d[k] for k in C.FEATURE_NAMES], dtype=np.float32)


def clip_windows(x):
    """Divide um clipe (int16) em janelas como o firmware: completa o último bloco de HOP
    com zeros; nº de janelas = blocos - 1. Retorna array (nwin, N) de int16."""
    x = np.asarray(x)
    nblk = -(-len(x) // C.HOP)
    if nblk < 2:
        return np.zeros((0, C.N), dtype=np.int16)
    pad = np.zeros(nblk * C.HOP, dtype=np.int16)
    pad[:len(x)] = x
    return np.stack([pad[i * C.HOP:i * C.HOP + C.N] for i in range(nblk - 1)])


def clip_features(x):
    """Lista de dicts (um por janela) para um clipe int16."""
    return [window_features(w) for w in clip_windows(x)]
