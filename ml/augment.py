"""Augmentation (SÓ no treino, semente fixa, no nível do clipe, antes das janelas).
Todas as funções recebem/retornam float32 em [-1, 1]."""
import numpy as np
from scipy.signal import butter, sosfilt, fftconvolve
from ml import config as C
from ml.gen_smoke_alarm import synth_rir


def set_peak_dbfs(x, db):
    return x * (10 ** (db / 20) / (np.abs(x).max() + 1e-9))


def rms(x):
    return float(np.sqrt(np.mean(x ** 2)) + 1e-9)


def add_noise(x, noise, snr_db, rng):
    """Soma um trecho de `noise` (repetido/cortado) com SNR dado (relativo ao RMS de x)."""
    if len(noise) < len(x):
        noise = np.tile(noise, int(np.ceil(len(x) / len(noise))))
    o = int(rng.integers(0, len(noise) - len(x) + 1))
    n = noise[o:o + len(x)]
    n = n * (rms(x) / rms(n)) * 10 ** (-snr_db / 20)
    return x + n


def time_shift(x, rng):
    return np.roll(x, int(rng.integers(0, len(x))))


def speaker_response(x, rng):
    """Passa-banda ~300 Hz–7 kHz (cantos aleatórios) + leve inclinação de EQ."""
    lo, hi = rng.uniform(200, 450), rng.uniform(5500, 7500)
    sos = butter(2, [lo, hi], btype="band", fs=C.FS, output="sos")
    y = sosfilt(sos, x)
    tilt = rng.uniform(-6, 6)                       # dB entre baixas e altas
    sos2 = butter(1, 2000, btype="low", fs=C.FS, output="sos")
    lowpart = sosfilt(sos2, y)
    g = 10 ** (tilt / 20)
    return (lowpart * (1 / g) + (y - lowpart) * g).astype(np.float32)


def reverb(x, rng):
    return fftconvolve(x, synth_rir(rng, rng.uniform(0.1, 0.6)))[:len(x)].astype(np.float32)


def light_clip(x, rng):
    thr = rng.uniform(0.6, 0.95) * np.abs(x).max()
    return np.clip(x, -thr, thr)


def augment_clip(x, rng, noise_pool, speech_pool=None, is_positive=False):
    """Aplica uma combinação aleatória. noise_pool: lista de clipes negativos (train).
    Para positivos, mistura o alarme sobre fala/ruído (imita a demo)."""
    x = x.astype(np.float32)
    if rng.random() < 0.5:
        x = time_shift(x, rng)
    if rng.random() < 0.4:
        x = reverb(x, rng)
    if rng.random() < 0.6:
        x = speaker_response(x, rng)
    x = x / (np.abs(x).max() + 1e-9)
    if is_positive and speech_pool and rng.random() < 0.4:
        bg = speech_pool[int(rng.integers(len(speech_pool)))]
        x = add_noise(x, bg, rng.uniform(0, 15), rng)       # alarme sobre fala
    elif noise_pool and rng.random() < 0.8:
        bg = noise_pool[int(rng.integers(len(noise_pool)))]
        x = add_noise(x, bg, rng.uniform(0, 30), rng)       # SNR 0-30 dB
    if rng.random() < 0.1:
        x = light_clip(x, rng)
    return set_peak_dbfs(x, rng.uniform(-40, -5)).astype(np.float32)
