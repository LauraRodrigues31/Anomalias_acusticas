"""Pipeline de dados: reamostra, divide POR CLIPE, augmenta o treino, rotula janelas e
grava manifestos + features por janela. Nada disso é versionado (data/processed/ é ignorado).

Saídas em data/processed/:
  clips/<split>/*.wav              clipes 16 kHz mono int16 (originais, sem augmentation)
  {train,val,test}_manifest.csv    path, label, type, source, clip_id
  windows_{train,val,test}.npz     features por janela: X, rms_db, band_power, clip_idx, win_idx, label
                                   (label: 1 alarme, 0 negativa, -1 excluída do treino)
  Em train, as variantes augmentadas entram com clip_idx próprio (aug=1 em windows_train.npz).
Uso: python -m ml.build_dataset [--limit N] [--aug-pos 3] [--aug-neg 1]
"""
import argparse
import glob
import hashlib
import os
import sys
import numpy as np
import pandas as pd
import soundfile as sf
from scipy.signal import resample_poly
from math import gcd
from ml import config as C
from ml import features as F
from ml import augment as A
from ml.gen_smoke_alarm import gen_alarm

RAW = os.path.join(C.ROOT, "data", "raw")
PROC = os.path.join(C.ROOT, "data", "processed")
SEED = 1234
HARD = {"clock_alarm", "siren", "car_horn", "church_bells", "door_wood_knock", "keyboard_typing",
        "mouse_click", "clapping", "glass_breaking", "crying_baby"}
MIN_REAL_WARN = 10


def load_wav(path):
    x, fs = sf.read(path, dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if fs != C.FS:
        g = gcd(C.FS, fs)
        x = resample_poly(x, C.FS // g, fs // g).astype(np.float32)
    return x


def to_i16(x):
    return np.clip(np.round(x * 32767), -32768, 32767).astype(np.int16)


def strat_split(items, rng, frac=(0.70, 0.15, 0.15)):
    """Divide lista em train/val/test aleatoriamente (semente fixa)."""
    idx = rng.permutation(len(items))
    n = len(items)
    a, b = int(round(frac[0] * n)), int(round((frac[0] + frac[1]) * n))
    out = {"train": [], "val": [], "test": []}
    for j, i in enumerate(idx):
        out["train" if j < a else "val" if j < b else "test"].append(items[i])
    return out


def collect(limit):
    """Retorna dict split -> lista de dicts(x=float32, label, type, source, name)."""
    rng = np.random.default_rng(SEED)
    S = {"train": [], "val": [], "test": []}

    def add(split, x, label, typ, source, name):
        S[split].append(dict(x=x, label=label, type=typ, source=source, name=name))

    # --- positivos sintéticos: HF + gerador próprio ---
    hf = sorted(glob.glob(os.path.join(RAW, "hf_synth_smoke", "data", "*.wav")))[:limit]
    gen_rng = np.random.default_rng(SEED + 1)
    gens = [(f"gen_{i:03d}",) for i in range(min(250, limit))]
    syn = [("hf", os.path.basename(p), p) for p in hf] + [("gen", g[0], None) for g in gens]
    for split, items in strat_split(syn, rng).items():
        for src, name, p in items:
            if src == "hf":
                x = load_wav(p)
            else:
                x, _ = gen_alarm(np.random.default_rng(int(name.split("_")[1]) + 10_000))
            add(split, x, 1, "positivo_sintetico", src, name)

    # --- positivos reais (Freesound via API), após curadoria (ml/curate_real.py) ---
    # Divisão por AUTOR (grupo): séries do mesmo autor/gravação são quase duplicatas e
    # vazariam entre treino e teste se divididas por clipe.
    fs_dir = os.path.join(RAW, "smoke_real")
    fs_files, fs_author = [], {}
    if os.path.exists(os.path.join(fs_dir, "SOURCES.csv")):
        srcs = pd.read_csv(os.path.join(fs_dir, "SOURCES.csv"))
        exc_path = os.path.join(fs_dir, "EXCLUDED.csv")
        excl = set(pd.read_csv(exc_path).file) if os.path.exists(exc_path) else set()
        for _, r in srcs.iterrows():
            if r.file not in excl:
                fs_files.append(os.path.join(fs_dir, r.file)); fs_author[os.path.join(fs_dir, r.file)] = r.author
        fs_files = fs_files[:limit]
    groups = {}
    for p in fs_files:
        groups.setdefault(fs_author[p], []).append(p)
    gl = [groups[k] for k in rng.permutation(sorted(groups))]
    tgt = {"train": 0.70 * len(fs_files), "val": 0.15 * len(fs_files), "test": 0.15 * len(fs_files)}
    got = {"train": 0, "val": 0, "test": 0}
    fs_split = {"train": [], "val": [], "test": []}
    for g in sorted(gl, key=len, reverse=True):     # maiores grupos primeiro, no split mais "faminto"
        sp = max(tgt, key=lambda k: tgt[k] - got[k])
        fs_split[sp] += g; got[sp] += len(g)
    for split, items in fs_split.items():
        for p in items:
            add(split, load_wav(p), 1, "positivo_real", "freesound", os.path.basename(p))
    # --- positivos reais MANUAIS: SÓ TESTE (nunca treino/validação) ---
    man = sorted(glob.glob(os.path.join(RAW, "smoke_real_manual", "*.wav")))
    for p in man:
        add("test", load_wav(p), 1, "positivo_real_manual", "manual", os.path.basename(p))
    n_real = len(fs_files) + len(man)   # já sem os excluídos pela curadoria
    if n_real < MIN_REAL_WARN:
        print(f"\n*** AVISO: só {n_real} clipes reais de alarme (< {MIN_REAL_WARN}). Avise a aluna antes de "
              f"decidir como reportar. Sem positivos reais o relatório "
              f"deve dizer isso. ***\n", file=sys.stderr)
    # (data/raw/demo/alarm_demo.wav NÃO é lido aqui: fica fora de tudo)

    # --- negativos: ESC-50 por folds oficiais ---
    meta = pd.read_csv(os.path.join(RAW, "ESC-50", "meta", "esc50.csv"))
    if limit < 10_000:
        meta = meta.groupby("category").head(max(1, limit // 50))
    for _, r in meta.iterrows():
        split = "train" if r.fold <= 3 else "val" if r.fold == 4 else "test"
        typ = "negativo_dificil" if r.category in HARD else "negativo_comum"
        add(split, load_wav(os.path.join(RAW, "ESC-50", "audio", r.filename)), 0, typ, "esc50",
            f"{r.category}/{r.filename}")

    # --- fala: mini_speech_commands, divisão por locutor; concatena 5 palavras (~5 s) ---
    spk = {}
    for p in glob.glob(os.path.join(RAW, "mini_speech_commands", "*", "*.wav")):
        spk.setdefault(os.path.basename(p).split("_")[0], []).append(p)
    spk_ids = sorted(spk)
    sp_split = strat_split(spk_ids, rng)
    n_utt = {"train": 210, "val": 45, "test": 45}
    for split, ids in sp_split.items():
        files = [p for s in ids for p in spk[s]]
        for u in range(min(n_utt[split], max(3, limit // 5))):
            parts = []
            for p in rng.choice(files, 5, replace=False):
                parts += [load_wav(p), np.zeros(int(rng.uniform(0.1, 0.4) * C.FS), np.float32)]
            x = np.concatenate(parts)
            add(split, A.set_peak_dbfs(x, rng.uniform(-30, -8)), 0, "negativo_comum", "speech", f"utt_{split}_{u:03d}")

    # --- ruído de sala sintético: branco/rosa/marrom ---
    for i in range(min(150, limit)):
        n = 5 * C.FS
        w = rng.standard_normal(n)
        kind = ["white", "pink", "brown"][i % 3]
        if kind == "pink":
            f = np.fft.rfft(w); f[1:] /= np.sqrt(np.arange(1, len(f))); w = np.fft.irfft(f, n)
        elif kind == "brown":
            f = np.fft.rfft(w); f[1:] /= np.arange(1, len(f)); w = np.fft.irfft(f, n)
        x = A.set_peak_dbfs(w.astype(np.float32), rng.uniform(-40, -10))
        split = "train" if i % 20 < 14 else "val" if i % 20 < 17 else "test"
        add(split, x, 0, "negativo_comum", "noise_" + kind, f"noise_{kind}_{i:03d}")
    return S


def window_table(x_f32, clip_idx, label, aug):
    """Features de todas as janelas de um clipe + rótulo por janela (regra da seção 9)."""
    d = F.clip_features(to_i16(x_f32))
    if not d:
        return None
    rms_db = np.array([w["rms_db"] for w in d], np.float32)
    bp = np.array([w["band_power"] for w in d], np.float32)
    X = np.stack([F.feature_vector(w) for w in d])
    lab = np.full(len(d), -1, np.int8)
    active = rms_db >= C.RMS_GATE_DB
    if label == 0:
        lab[active] = 0
    else:
        bmax = bp.max() + 1e-30
        near = 10 * np.log10(bp / bmax + 1e-30) >= -20.0         # a menos de 20 dB do máximo
        lab[active & near] = 1                                     # pausas entre bipes ficam -1
    n = len(d)
    return dict(X=X, rms_db=rms_db, band_power=bp, clip_idx=np.full(n, clip_idx, np.int32),
                win_idx=np.arange(n, dtype=np.int32), label=lab, aug=np.full(n, aug, np.int8))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10**9, help="limita itens por fonte (teste rápido)")
    ap.add_argument("--aug-pos", type=int, default=3)
    ap.add_argument("--aug-neg", type=int, default=1)
    a = ap.parse_args()
    os.makedirs(PROC, exist_ok=True)
    S = collect(a.limit)
    rng = np.random.default_rng(SEED + 7)
    noise_pool = [c["x"] for c in S["train"] if c["label"] == 0 and c["type"] == "negativo_comum" and c["source"] != "speech"]
    speech_pool = [c["x"] for c in S["train"] if c["source"] == "speech"]

    for split, clips in S.items():
        cdir = os.path.join(PROC, "clips", split)
        os.makedirs(cdir, exist_ok=True)
        rows, tabs = [], []
        for ci, c in enumerate(clips):
            fn = f"{ci:05d}.wav"
            path = os.path.join(cdir, fn)
            sf.write(path, to_i16(c["x"]), C.FS, subtype="PCM_16")
            rows.append(dict(clip_idx=ci, path=os.path.relpath(path, C.ROOT), label=c["label"], type=c["type"],
                             source=c["source"], name=c["name"]))
            t = window_table(c["x"], ci, c["label"], 0)
            if t: tabs.append(t)
            if split == "train":     # augmentation SÓ no treino; variantes herdam o clip_idx do original
                for _ in range(a.aug_pos if c["label"] == 1 else a.aug_neg):
                    xa = A.augment_clip(c["x"], rng, noise_pool, speech_pool, is_positive=c["label"] == 1)
                    t = window_table(xa, ci, c["label"], 1)
                    if t: tabs.append(t)
        pd.DataFrame(rows).to_csv(os.path.join(PROC, f"{split}_manifest.csv"), index=False)
        np.savez_compressed(os.path.join(PROC, f"windows_{split}.npz"),
                            **{k: np.concatenate([t[k] for t in tabs]) for k in tabs[0]})
        df = pd.DataFrame(rows)
        w = np.load(os.path.join(PROC, f"windows_{split}.npz"))
        print(f"[{split}] clipes={len(df)}  janelas={len(w['label'])}  "
              f"pos={int((w['label']==1).sum())} neg={int((w['label']==0).sum())} excl={int((w['label']==-1).sum())}")
        print(df.groupby(["type", "source"]).size().to_string())
    print("ok")


if __name__ == "__main__":
    main()
