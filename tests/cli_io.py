"""Utilitários de protocolo (docs/serial_protocol.md): executa o dsp_cli nativo e interpreta W/A/S."""
import os
import subprocess
import numpy as np
from ml import config as C

# DSP_CLI permite apontar para um binário compilado à mão (sem pio); o padrão é o do env native-cli
CLI = os.environ.get("DSP_CLI") or os.path.join(C.ROOT, "firmware", ".pio", "build", "native-cli", "program")
W_COLS = ["clip", "win", "t_block_ready_us", "rms_db", "centroid_norm", "band_ratio", "band_peakiness",
          "peak_freq_norm", "prob", "pos", "t_sched_us", "t_feat_us", "t_queue_us", "t_infer_us", "t_total_us"]


def parse_line(line, out):
    """Interpreta uma linha W/A/S/DONE e acumula em out (dict com listas)."""
    p = line.strip().split(",")
    if not p or not p[0]:
        return
    if p[0] == "W" and len(p) == 16:
        row = dict(zip(W_COLS, p[1:]))
        for k in W_COLS[1:]:
            row[k] = float(row[k])
        out["W"].append(row)
    elif p[0] == "A" and len(p) == 5:
        out["A"].append(dict(clip=p[1], win=int(p[2]), t_alert_us=int(p[3]), t_decision_us=int(p[4])))
    elif p[0] == "S" and len(p) == 8:
        out["S"] = [int(v) for v in p[1:]]


def run_native(clips, cli=CLI):
    """clips: lista de (clip_id, int16 array). Retorna dict clip_id -> {"W","A","S"}."""
    if not os.path.exists(cli):
        raise FileNotFoundError(f"{cli} não existe. Rode: (cd firmware && pio run -e native-cli)")
    buf = bytearray()
    for cid, x in clips:
        x = np.asarray(x, dtype="<i2")
        buf += f"START {cid} {len(x)}\n".encode() + x.tobytes()
    res = subprocess.run([cli], input=bytes(buf), capture_output=True, check=True)
    results = {}
    cur = None
    for line in res.stdout.decode().splitlines():
        if line.startswith("DONE"):
            cur = None
            continue
        p = line.split(",")
        if p[0] in ("W", "A"):
            cid = p[1]
            cur = results.setdefault(cid, {"W": [], "A": [], "S": None})
        if cur is not None:
            parse_line(line, cur)
    return results
