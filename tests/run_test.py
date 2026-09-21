"""Harness de teste e medição de desempenho (seção 8 do CLAUDE.md).

  python tests/run_test.py --target native                       # dsp_cli no PC (tempos = HOST)
  python tests/run_test.py --target serial:/dev/ttyUSB0          # ESP32 (NÃO VALIDADO em hardware)
  python tests/run_test.py --target native --simulate-anomalies  # cenas de 10 s com alarme em instante conhecido
  python tests/run_test.py --target native --demo-clip data/raw/demo/alarm_demo.wav

Resultados: docs/results/<modo>_<carimbo>_<alvo>.{json,csv,png}. No alvo native os tempos usam
std::chrono do PC e NÃO representam o ESP32. Números do ESP32 só existem depois que a aluna roda
--target serial na placa.
"""
import argparse
import json
import os
import sys
import time
import numpy as np
import pandas as pd
import soundfile as sf
from scipy.signal import resample_poly
from math import gcd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ml import config as C
from ml import evaluate as E
from ml.gen_smoke_alarm import gen_alarm
from tests.cli_io import run_native, parse_line

RES = os.path.join(C.ROOT, "docs", "results")
STAGES = ["t_sched_us", "t_feat_us", "t_queue_us", "t_infer_us", "t_total_us"]
HOST_NOTE = "host (PC): NÃO representa o ESP32"


# ------------------------------------------------------------------ alvos ----------------------
class NativeTarget:
    name = "native"
    label = HOST_NOTE
    realtime_wall = False

    def run(self, clips, **_):
        return run_native(clips)


class SerialTarget:
    """ESP32 com o firmware esp32-test. NÃO VALIDADO em hardware até a aluna testar na placa.
    Protocolo: docs/serial_protocol.md. Envia em tempo real (um bloco de 512 amostras a cada 32 ms)
    ou --fast (bloco a cada 8 ms; T1 do firmware faz contrapressão)."""
    name = "esp32"
    label = "ESP32 (serial) — tempos medidos na placa"
    realtime_wall = True

    def __init__(self, port, baud=921600, fast=False):
        import serial
        import threading
        import queue
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.fast = fast
        self.q = queue.Queue()
        self._stop = False
        self.t = threading.Thread(target=self._reader, daemon=True)
        time.sleep(2.0)                       # o ESP32 reinicia ao abrir a porta
        self.ser.reset_input_buffer()
        self.t.start()

    def _reader(self):
        buf = b""
        while not self._stop:
            try:
                buf += self.ser.read(4096)
            except Exception:      # porta fechada ao encerrar
                return
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.q.put((time.perf_counter(), line.decode(errors="replace").strip()))

    def run(self, clips, on_progress=None, **_):
        out = {}
        blk_s = C.HOP / C.FS
        pace = blk_s / (4 if self.fast else 1)
        for n, (cid, x) in enumerate(clips):
            x = np.asarray(x, dtype="<i2")
            cur = {"W": [], "A": [], "S": None, "wall": {}}
            out[str(cid)] = cur
            self.ser.write(f"START {cid} {len(x)}\n".encode())
            t0 = time.perf_counter()
            for i in range(0, len(x), C.HOP):
                self.ser.write(x[i:i + C.HOP].tobytes())
                time.sleep(max(0.0, t0 + (i // C.HOP + 1) * pace - time.perf_counter()))
            t_end = time.perf_counter() + 15.0
            while time.perf_counter() < t_end:
                try:
                    th, line = self.q.get(timeout=0.2)
                except Exception:
                    continue
                if line.startswith("DONE"):
                    break
                if line.startswith(("W,", "A,", "S,")):
                    if line.startswith("A,"):
                        cur["wall"][int(line.split(",")[2])] = th - t0
                    parse_line(line, cur)
            if on_progress:
                on_progress(n + 1, len(clips))
        # O dsp_cli/fake_esp32 responde S com stack = -1 (não existe RTOS): não é hardware.
        if any(r["S"] and r["S"][3] < 0 for r in out.values()):
            self.name = "dispositivo-falso"
            self.label = "DISPOSITIVO FALSO (teste do lado do host) — NÃO é o ESP32"
        return out

    def close(self):
        self._stop = True
        self.ser.close()


# ------------------------------------------------------------------ utilidades ------------------
def load_i16(path):
    x, fs = sf.read(path, dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if fs != C.FS:
        g = gcd(C.FS, fs)
        x = resample_poly(x, C.FS // g, fs // g).astype(np.float32)
    return np.clip(np.round(x * 32767), -32768, 32767).astype(np.int16)


def stats(v):
    v = np.asarray([a for a in v if a is not None and a >= 0], dtype=float)
    if len(v) == 0:
        return None
    return dict(n=int(len(v)), mean=float(v.mean()), p50=float(np.percentile(v, 50)),
                p95=float(np.percentile(v, 95)), max=float(v.max()))


def latency_table(results):
    rows = [w for r in results.values() for w in r["W"]]
    tab = {}
    for s in STAGES:
        tab[s] = stats([w[s] for w in rows])
    tab["t_decision_us"] = stats([a["t_decision_us"] for r in results.values() for a in r["A"]])
    return tab


def stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def plot_latency(tab, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ks = [k for k in STAGES if tab.get(k)]
    if not ks:
        return
    fig, ax = plt.subplots(figsize=(7, 3.5))
    x = np.arange(len(ks))
    ax.bar(x - 0.2, [tab[k]["p50"] for k in ks], 0.4, label="p50")
    ax.bar(x + 0.2, [tab[k]["p95"] for k in ks], 0.4, label="p95")
    ax.set_xticks(x, [k.replace("_us", "") for k in ks]); ax.set_ylabel("µs"); ax.legend(); ax.set_title(title, fontsize=9)
    ax.axhline(32000, color="r", ls="--", lw=.8)
    ax.text(0, 32000, " passo entre janelas (32 ms)", color="r", fontsize=7, va="bottom")
    fig.tight_layout(); fig.savefig(path, dpi=120); plt.close(fig)


# ------------------------------------------------------------------ modos -----------------------
def mode_manifest(tg, a):
    man = pd.read_csv(os.path.join(C.ROOT, "data", "processed", f"{a.split}_manifest.csv"))
    if a.max_per_type:
        man = man.groupby("type", group_keys=False).head(a.max_per_type)
    clips = [(int(r.clip_idx), load_i16(os.path.join(C.ROOT, r.path))) for r in man.itertuples()]
    t0 = time.time()
    res = tg.run(clips, on_progress=lambda i, n: print(f"\r{i}/{n} clipes", end="", flush=True))
    print(f"\nprocessado em {time.time() - t0:.1f} s de parede")
    dec = {int(cid): len(r["A"]) > 0 for cid, r in res.items()}
    cm = E.clip_metrics(man, dec)
    lat = latency_table(res)
    S = [r["S"] for r in res.values() if r["S"]]
    counters = None
    if S and tg.name == "esp32":
        last = S[-1]
        counters = dict(overruns=last[0], queue_drops=last[1], mutex_timeouts=last[2],
                        stack_free_bytes=dict(T1=last[3], T2=last[4], T3=last[5], T4=last[6]))
    out = dict(modo="manifest", split=a.split, alvo=tg.name, alvo_descricao=tg.label, carimbo=stamp(),
               validado_em_hardware=(tg.name == "esp32" and False),
               n_clipes=len(man), clip=cm, latencia_us=lat, contadores_esp32=counters)
    base = os.path.join(RES, f"teste_{a.split}_{out['carimbo']}_{tg.name}")
    save(out, base, lat, man.assign(alerta=[dec.get(int(i), False) for i in man.clip_idx]), tg)
    g = cm["global"]
    print(f"[{tg.label}] split={a.split} clipes={len(man)}  recall={g['recall']}  FPR={g['fpr']}  acc={g['accuracy']:.3f}")
    for t, v in cm.items():
        if t != "global":
            print(f"  {t:22s} n={v['n']:4d} tp={v['tp']} fn={v['fn']} fp={v['fp']} tn={v['tn']}")
    print_lat(lat, tg)


def print_lat(lat, tg):
    print(f"latências ({tg.label}) em µs:")
    for k, v in lat.items():
        if v:
            print(f"  {k:14s} n={v['n']:6d} mean={v['mean']:9.1f} p50={v['p50']:9.1f} p95={v['p95']:9.1f} max={v['max']:9.1f}")


def save(out, base, lat, df, tg):
    os.makedirs(RES, exist_ok=True)
    json.dump(out, open(base + ".json", "w"), indent=2, ensure_ascii=False, default=float)
    if df is not None:
        df.to_csv(base + ".csv", index=False)
    plot_latency(lat, base + ".png", f"Latência por etapa — {tg.label}")
    print("gravado:", os.path.relpath(base, C.ROOT) + ".{json,csv,png}")


def make_scene(rng, bg, snr_db, seed):
    """Cena de 10 s: fundo (negativo) + alarme sintético inserido em instante aleatório conhecido."""
    n = 10 * C.FS
    if len(bg) < n:
        bg = np.tile(bg, int(np.ceil(n / len(bg))))
    o = int(rng.integers(0, len(bg) - n + 1))
    bg = bg[o:o + n].astype(np.float32) / 32768
    bg = bg * (10 ** (rng.uniform(-35, -18) / 20) / (np.abs(bg).max() + 1e-9))
    al, info = gen_alarm(np.random.default_rng(seed), dur_s=5.0)
    on = int(np.argmax(np.abs(al) > 0.05 * np.abs(al).max()))     # início real do 1º bipe
    t0 = int(rng.uniform(2.0, 4.5) * C.FS)
    al = al * (np.sqrt(np.mean(bg ** 2)) * 10 ** (snr_db / 20) / (np.sqrt(np.mean(al[al != 0] ** 2)) + 1e-9))
    sc = bg.copy()
    L = min(len(al), n - t0)
    sc[t0:t0 + L] += al[:L]
    onset_s = (t0 + on) / C.FS
    return np.clip(np.round(sc * 32768), -32768, 32767).astype(np.int16), onset_s, info


def mode_simulate(tg, a):
    rng = np.random.default_rng(2026)
    man = pd.read_csv(os.path.join(C.ROOT, "data", "processed", f"{a.split}_manifest.csv"))
    neg = man[man.label == 0].reset_index(drop=True)
    snrs = [0, 5, 10, 20]
    scenes = []
    for i in range(a.n_scenes):
        r = neg.iloc[int(rng.integers(len(neg)))]
        sc, onset, info = make_scene(rng, load_i16(os.path.join(C.ROOT, r.path)), snrs[i % len(snrs)], 50_000 + i)
        scenes.append(dict(id=i, x=sc, onset_s=onset, snr=snrs[i % len(snrs)], bg=r["name"], pattern=info["pattern"]))
    res = tg.run([(s["id"], s["x"]) for s in scenes])
    rows = []
    for s in scenes:
        r = res[str(s["id"])]
        # 1º alerta APÓS o início do alarme (alertas antes seriam falsos alarmes do fundo)
        alerts = [x for x in r["A"] if x["t_alert_us"] / 1e6 >= s["onset_s"]]
        early = [x for x in r["A"] if x["t_alert_us"] / 1e6 < s["onset_s"]]
        if tg.name == "native":
            t_alert = alerts[0]["t_alert_us"] / 1e6 if alerts else None
            d_audio = (t_alert - s["onset_s"]) if alerts else None
            d_wall = None
        else:
            # ESP32: t_alert vem do relógio do próprio ESP (µs desde o boot); use o t_block_ready da
            # janela para ancorar a linha do tempo do áudio
            w0 = r["W"][0]["t_block_ready_us"] if r["W"] else 0
            t_alert = ((alerts[0]["t_alert_us"] - w0) / 1e6 + C.N / C.FS) if alerts else None
            d_audio = (t_alert - s["onset_s"]) if alerts else None
            d_wall = r["wall"].get(alerts[0]["win"]) if alerts else None
            d_wall = (d_wall - s["onset_s"]) if d_wall is not None else None
        rows.append(dict(scene=s["id"], snr_db=s["snr"], padrao=s["pattern"], fundo=s["bg"], onset_s=round(s["onset_s"], 3),
                         detectou=bool(alerts), falso_alarme_antes=len(early) > 0,
                         atraso_audio_s=d_audio, atraso_parede_s=d_wall))
    df = pd.DataFrame(rows)
    summ = {}
    for snr, g in df.groupby("snr_db"):
        d = g.atraso_audio_s.dropna()
        summ[int(snr)] = dict(cenas=len(g), detectadas=int(g.detectou.sum()), taxa=float(g.detectou.mean()),
                              atraso_audio_s=stats(d.values * 1000 if len(d) else []) and {k: (v / 1000 if k != "n" else v) for k, v in stats(d.values * 1000).items()},
                              falsos_antes=int(g.falso_alarme_antes.sum()))
    lat = latency_table(res)
    out = dict(modo="simulate_anomalies", split=a.split, alvo=tg.name, alvo_descricao=tg.label, carimbo=stamp(),
               validado_em_hardware=False, n_cenas=len(df), por_snr=summ, latencia_us=lat,
               nota="atraso_audio = ALERTA - início do alarme, na linha do tempo do áudio; inclui a latência inerente "
                    "da janela (64 ms) e o voto N de M. atraso_parede só existe no alvo serial (tempo real).")
    base = os.path.join(RES, f"simulacao_{out['carimbo']}_{tg.name}")
    save(out, base, lat, df, tg)
    print(df.groupby("snr_db").agg(cenas=("scene", "count"), detectadas=("detectou", "sum"),
                                   atraso_medio_s=("atraso_audio_s", "mean")).to_string())
    print_lat(lat, tg)


def mode_demo(tg, a):
    from ml import model as M
    x = load_i16(a.demo_clip)
    res = tg.run([(0, x)])["0"]
    p = M.load_params()
    print(f"clipe {a.demo_clip}: {len(x) / C.FS:.1f} s | modelo: thr={p['prob_threshold']} N={p['vote_n']} de M={p['vote_m']} | {tg.label}")
    alerts = {x_["win"]: x_ for x_ in res["A"]}
    print(" win   t(s)  rms_db   prob  pos  alerta")
    for w in res["W"]:
        i = int(w["win"])
        print(f"{i:4d} {w['t_block_ready_us'] / 1e6:6.2f} {w['rms_db']:7.1f} {w['prob']:6.2f}  {int(w['pos'])}    {'ALERTA' if i in alerts else ''}")
    print("DECISÃO:", "ALARME DETECTADO" if res["A"] else "sem alerta")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="native", help="native | serial:<porta>")
    ap.add_argument("--split", default="test", choices=["val", "test"])
    ap.add_argument("--max-per-type", type=int, default=0, help="limita clipes por tipo (ensaios na placa)")
    ap.add_argument("--simulate-anomalies", action="store_true")
    ap.add_argument("--n-scenes", type=int, default=40)
    ap.add_argument("--demo-clip")
    ap.add_argument("--fast", action="store_true", help="serial: envia 4x mais rápido que o tempo real")
    a = ap.parse_args()
    if a.target == "native":
        tg = NativeTarget()
    elif a.target.startswith("serial:"):
        print("AVISO: alvo serial NÃO foi validado em hardware.")
        tg = SerialTarget(a.target.split(":", 1)[1], fast=a.fast)
    else:
        ap.error("--target deve ser native ou serial:<porta>")
    try:
        if a.demo_clip:
            mode_demo(tg, a)
        elif a.simulate_anomalies:
            mode_simulate(tg, a)
        else:
            mode_manifest(tg, a)
    finally:
        if hasattr(tg, "close"):
            tg.close()


if __name__ == "__main__":
    main()
