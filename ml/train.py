"""Treino: StandardScaler + LogisticRegression(class_weight="balanced").
C, limiar de probabilidade e (N, M) são escolhidos SOMENTE na validação (por clipe).
O teste não é lido aqui. Uso: python -m ml.train [--features 4|extra]"""
import argparse
import json
import os
import time
import numpy as np
import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from ml import config as C
from ml import evaluate as E

MODELS = os.path.join(C.ROOT, "models")
C_GRID = [0.01, 0.1, 1.0, 10.0, 100.0]
THR_GRID = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98, 0.99]
NM_GRID = [(3, 5), (2, 3), (4, 5), (5, 8), (6, 8)]
FPR_BUDGET = 0.03     # margem sob a meta de 5% (o teste terá outra amostra)


def fit(C_, Xtr, ytr):
    pipe = make_pipeline(StandardScaler(), LogisticRegression(C=C_, class_weight="balanced", max_iter=2000))
    return pipe.fit(Xtr, ytr)


def params_from(pipe, C_, thr, n, m, extra):
    sc, lr = pipe.steps[0][1], pipe.steps[1][1]
    d = dict(mean=sc.mean_.tolist(), std=sc.scale_.tolist(), w=lr.coef_[0].tolist(), b=float(lr.intercept_[0]),
             prob_threshold=float(thr), vote_n=int(n), vote_m=int(m), C=float(C_),
             feature_names=C.FEATURE_NAMES)
    d.update(extra)
    return d


def main():
    ap = argparse.ArgumentParser()
    a = ap.parse_args()
    wtr, _ = E.load_split("train")
    wva, mva = E.load_split("val")
    sel = wtr["label"] >= 0
    Xtr, ytr = wtr["X"][sel], wtr["label"][sel]
    print(f"treino: {len(ytr)} janelas ({int(ytr.sum())} positivas)")
    slv = E.clip_slices(wva)
    vsel = (wva["aug"] == 0) & (wva["label"] >= 0)

    # 1) C: melhor precisão média (PR-AUC) por janela na validação
    best = None
    for c in C_GRID:
        pipe = fit(c, Xtr, ytr)
        p = pipe.predict_proba(wva["X"][vsel])[:, 1]
        ap_ = average_precision_score(wva["label"][vsel], p)
        print(f"  C={c:<7} PR-AUC(val, janela)={ap_:.4f}")
        if best is None or ap_ > best[0]:
            best = (ap_, c, pipe)
    _, C_, pipe = best
    print("C escolhido:", C_)

    # 2) limiar e N/M: por clipe na validação; maximiza recall com FPR <= orçamento
    params0 = params_from(pipe, C_, 0.5, 3, 5, {})
    probs = E.window_probs(wva, params0)
    cands = []
    for thr in THR_GRID:
        for n, m in NM_GRID:
            dec = E.clip_decisions(wva, probs, slv, thr, n, m)
            g = E.clip_metrics(mva, dec)["global"]
            cands.append((thr, n, m, g["recall"], g["fpr"]))
    ok = [c for c in cands if c[4] <= FPR_BUDGET]
    pool = ok if ok else sorted(cands, key=lambda c: c[4])[:5]
    # maior recall; empate: menor FPR; depois limiar maior; depois preferir (3,5)
    thr, n, m, rec, fpr = sorted(pool, key=lambda c: (-c[3], c[4], -c[0], (c[1], c[2]) != (3, 5)))[0]
    print(f"escolhido na validação: thr={thr} N={n} M={m} -> recall={rec:.3f} FPR={fpr:.3f}"
          f"{'' if ok else '  (NENHUMA combinação atingiu FPR<=%.2f)' % FPR_BUDGET}")

    params = params_from(pipe, C_, thr, n, m, dict(trained_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                                                   n_train_windows=int(len(ytr))))
    os.makedirs(MODELS, exist_ok=True)
    joblib.dump(pipe, os.path.join(MODELS, "detector.joblib"))
    json.dump(params, open(os.path.join(MODELS, "model_params.json"), "w"), indent=2)
    print("gravado models/model_params.json e models/detector.joblib")


if __name__ == "__main__":
    main()
