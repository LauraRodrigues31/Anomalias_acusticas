"""Avaliação por janela e por clipe. Funções de biblioteca + CLI.

Clipe = "houve pelo menos um ALERTA" (regra N de M sobre as janelas, com gate de RMS).
O cooldown não muda o "pelo menos um alerta" e por isso não entra aqui.

CLI:  python -m ml.evaluate --split val            (livre, quantas vezes quiser)
      python -m ml.evaluate --split test           (UMA vez; cria models/.test_used)
"""
import argparse
import json
import os
import sys
import time
import numpy as np
import pandas as pd
from ml import config as C
from ml import model as M

PROC = os.path.join(C.ROOT, "data", "processed")
RES = os.path.join(C.ROOT, "docs", "results")
TEST_LOCK = os.path.join(C.ROOT, "models", ".test_used")
TYPES = ["positivo_sintetico", "positivo_real", "positivo_real_manual", "negativo_comum", "negativo_dificil"]


def load_split(split):
    w = np.load(os.path.join(PROC, f"windows_{split}.npz"))
    man = pd.read_csv(os.path.join(PROC, f"{split}_manifest.csv"))
    return {k: w[k] for k in w.files}, man


def clip_slices(w):
    """Índices [ini, fim) de cada clipe (apenas aug=0), na ordem de clip_idx."""
    ci = w["clip_idx"]
    sel = np.flatnonzero(w["aug"] == 0)
    ci = ci[sel]
    cuts = np.flatnonzero(np.diff(ci)) + 1
    starts = np.r_[0, cuts]
    ends = np.r_[cuts, len(ci)]
    return {int(ci[s]): sel[s:e] for s, e in zip(starts, ends)}


def window_probs(w, params):
    return M.predict(params, w["X"]).astype(np.float32)


def clip_alert(pos, n, m):
    """Há alerta se em alguma janela a soma das últimas m (parcial no início) >= n."""
    if len(pos) == 0:
        return False
    cs = np.cumsum(pos.astype(np.int32))
    prev = np.r_[np.zeros(m, np.int32), cs][: len(cs)]       # cs[i-m]
    return bool(np.any(cs - prev >= n))


def clip_decisions(w, probs, slices, thr, n, m):
    """dict clip_idx -> bool alerta."""
    out = {}
    gate = w["rms_db"] >= C.RMS_GATE_DB
    for ci, idx in slices.items():
        pos = gate[idx] & (probs[idx] >= thr)
        out[ci] = clip_alert(pos, n, m)
    return out


def clip_metrics(man, dec):
    """Métricas por clipe globais e por tipo."""
    y = man["label"].values
    pred = np.array([dec.get(int(i), False) for i in man["clip_idx"]])
    def m(mask):
        yy, pp = y[mask], pred[mask]
        tp = int(((yy == 1) & pp).sum()); fn = int(((yy == 1) & ~pp).sum())
        fp = int(((yy == 0) & pp).sum()); tn = int(((yy == 0) & ~pp).sum())
        return dict(n=int(mask.sum()), tp=tp, fn=fn, fp=fp, tn=tn,
                    recall=tp / (tp + fn) if tp + fn else None, fpr=fp / (fp + tn) if fp + tn else None,
                    precision=tp / (tp + fp) if tp + fp else None,
                    accuracy=(tp + tn) / max(1, mask.sum()))
    out = {"global": m(np.ones(len(y), bool))}
    for t in TYPES:
        mk = (man["type"] == t).values
        if mk.any():
            out[t] = m(mk)
    return out


def window_metrics(w, probs, thr):
    lab = w["label"]; sel = (w["aug"] == 0) & (lab >= 0)
    y, p = lab[sel], probs[sel] >= thr
    tp = int(((y == 1) & p).sum()); fp = int(((y == 0) & p).sum())
    fn = int(((y == 1) & ~p).sum()); tn = int(((y == 0) & ~p).sum())
    return dict(n=int(sel.sum()), tp=tp, fp=fp, fn=fn, tn=tn, recall=tp / max(1, tp + fn),
                precision=tp / max(1, tp + fp), fpr=fp / max(1, fp + tn))


def hard_by_category(man, dec):
    """FPR por categoria ESC-50 (para achar o que dispara falso alarme)."""
    neg = man[man.label == 0].copy()
    neg["pred"] = [dec.get(int(i), False) for i in neg["clip_idx"]]
    neg["cat"] = neg["name"].str.split("/").str[0]
    g = neg[neg.source == "esc50"].groupby("cat")["pred"].agg(["sum", "count"])
    return g[g["sum"] > 0].sort_values("sum", ascending=False)


def plots(w, man, probs, dec, params, tag):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import precision_recall_curve
    os.makedirs(RES, exist_ok=True)
    sel = (w["aug"] == 0) & (w["label"] >= 0)
    pr, rc, _ = precision_recall_curve(w["label"][sel], probs[sel])
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    ax[0].plot(rc, pr); ax[0].set_xlabel("recall (janela)"); ax[0].set_ylabel("precisão (janela)")
    ax[0].set_title(f"Curva precisão-recall ({tag})"); ax[0].grid(alpha=.3)
    cm = clip_metrics(man, dec)["global"]
    mat = np.array([[cm["tn"], cm["fp"]], [cm["fn"], cm["tp"]]])
    ax[1].imshow(mat, cmap="Blues")
    for i in range(2):
        for j in range(2):
            ax[1].text(j, i, str(mat[i, j]), ha="center", va="center", fontsize=14)
    ax[1].set_xticks([0, 1], ["sem alerta", "alerta"]); ax[1].set_yticks([0, 1], ["negativo", "alarme"])
    ax[1].set_title(f"Matriz de confusão por clipe ({tag})")
    fig.tight_layout()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(RES, f"{tag}_confusao_pr_{stamp}_host.png")
    fig.savefig(path, dpi=120); plt.close(fig)
    return path


def report(split, params, thr=None, n=None, m=None):
    w, man = load_split(split)
    thr = params["prob_threshold"] if thr is None else thr
    n = params["vote_n"] if n is None else n
    m = params["vote_m"] if m is None else m
    probs = window_probs(w, params)
    sl = clip_slices(w)
    dec = clip_decisions(w, probs, sl, thr, n, m)
    return dict(split=split, thr=thr, vote_n=n, vote_m=m, clip=clip_metrics(man, dec),
                window=window_metrics(w, probs, thr)), (w, man, probs, dec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["val", "test"], required=True)
    ap.add_argument("--allow-test-rerun", action="store_true")
    a = ap.parse_args()
    if a.split == "test":
        if os.path.exists(TEST_LOCK) and not a.allow_test_rerun:
            print("O conjunto de teste já foi usado (models/.test_used). Não rode de novo para ajustar nada.")
            return 1
    params = M.load_params()
    rep, (w, man, probs, dec) = report(a.split, params)
    rep["model"] = {k: params[k] for k in ("C", "prob_threshold", "vote_n", "vote_m", "feature_names") if k in params}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    rep["alvo"] = "host (PC): métricas de acurácia independem do alvo; nenhum tempo do ESP32 aqui"
    rep["carimbo"] = stamp
    os.makedirs(RES, exist_ok=True)
    out = os.path.join(RES, f"{a.split}_report_{stamp}_host.json")
    json.dump(rep, open(out, "w"), indent=2, ensure_ascii=False)
    print(json.dumps(rep["clip"], indent=1, ensure_ascii=False))
    print("janela:", rep["window"])
    print("por categoria ESC-50 com falso alarme:\n", hard_by_category(man, dec).to_string())
    print("figura:", plots(w, man, probs, dec, params, a.split)); print("json:", out)
    if a.split == "test":
        open(TEST_LOCK, "w").write(f"test usado em {stamp}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
