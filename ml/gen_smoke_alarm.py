"""Gerador sintético de alarme de fumaça (semente fixa). Saída: float32 em [-1,1], 16 kHz.

Parâmetros: piezo 2,8-3,5 kHz, padrões T3 (3 bipes + pausa), T4 (4 bipes) e contínuo,
harmônicos, envelope, pequena deriva de frequência, reverberação (RIR exponencial, RT60 0,1-0,6 s).
"""
import numpy as np
from scipy.signal import fftconvolve
from ml import config as C


def synth_rir(rng, rt60):
    n = int(rt60 * C.FS)
    t = np.arange(n) / C.FS
    h = rng.standard_normal(n) * np.exp(-6.9078 * t / rt60)   # -60 dB em rt60
    h[0] = 1.0
    return h / np.sqrt(np.sum(h ** 2))


def beep(rng, f0, dur, drift, n_harm):
    n = int(dur * C.FS)
    t = np.arange(n) / C.FS
    f = f0 * (1.0 + drift * np.sin(2 * np.pi * rng.uniform(0.2, 1.0) * t + rng.uniform(0, 6.28)))
    ph = 2 * np.pi * np.cumsum(f) / C.FS
    x = np.sin(ph)
    for h in range(2, n_harm + 1):
        x += rng.uniform(0.05, 0.4) / h * np.sin(h * ph)
    a = int(0.005 * C.FS)                                   # ataque/soltura de 5 ms
    env = np.ones(n); env[:a] = np.linspace(0, 1, a); env[-a:] = np.linspace(1, 0, a)
    return x * env


def gen_alarm(rng, dur_s=8.0, pattern=None, f0=None, reverb=True):
    """Retorna (audio float32, info dict)."""
    pattern = pattern or rng.choice(["T3", "T3", "T4", "cont"])
    f0 = f0 or rng.uniform(2800, 3500)
    drift = rng.uniform(0, 0.01)
    n_harm = int(rng.integers(1, 4))
    bd = rng.uniform(0.4, 0.55)                              # duração do bipe
    gap = rng.uniform(0.15, 0.3)
    pause = rng.uniform(1.0, 1.7)
    total = int(dur_s * C.FS)
    x = np.zeros(total + C.FS)
    pos = int(rng.uniform(0, 0.5) * C.FS)
    while pos < total:
        if pattern == "cont":
            b = beep(rng, f0, min(dur_s - pos / C.FS, 3.0), drift, n_harm)
            x[pos:pos + len(b)] += b; pos += len(b) + int(0.5 * C.FS)
            continue
        for _ in range(3 if pattern == "T3" else 4):
            b = beep(rng, f0, bd, drift, n_harm)
            if pos + len(b) > len(x): break
            x[pos:pos + len(b)] += b
            pos += len(b) + int(gap * C.FS)
        pos += int(pause * C.FS)
    x = x[:total]
    rt60 = rng.uniform(0.1, 0.6) if reverb else 0.0
    if reverb:
        x = fftconvolve(x, synth_rir(rng, rt60))[:total]
    x = x / (np.abs(x).max() + 1e-9)
    return x.astype(np.float32), dict(pattern=str(pattern), f0=float(f0), rt60=float(rt60))
