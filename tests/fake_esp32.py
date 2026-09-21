"""Dispositivo serial FALSO para testar o lado do host de `run_test.py --target serial` sem placa.
Cria um pty e liga-o ao dsp_cli nativo (mesmo protocolo START/W/A/S/DONE). NÃO mede nada do ESP32.
Uso: python tests/fake_esp32.py   (imprime o caminho do pty; deixe rodando e use --target serial:<caminho>)

Modo --live <arquivo.wav> [--speed N]: simula o firmware de PRODUÇÃO ao vivo (áudio em laço; comandos
GATE/THR/VOTE/MON/STATS; linhas M/P/S/A) para testar tests/calibrate.py sem placa. Usa o mesmo interpretador
de comandos e a mesma decisão do firmware (dsp_cli --live). Não mede nada do ESP32."""
import argparse
import tempfile
import os
import pty
import subprocess
import sys
import threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.cli_io import CLI

master, slave = pty.openpty()
import tty
tty.setraw(master)
print(os.ttyname(slave), flush=True)
ap = argparse.ArgumentParser()
ap.add_argument("--live", help="WAV a tocar em laço (modo produção simulado)")
ap.add_argument("--speed", type=float, default=1.0, help="fator de velocidade do modo --live")
args = ap.parse_args()
cmd = [CLI]
if args.live:
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    x, fs = sf.read(args.live, dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if fs != 16000:
        g = gcd(16000, fs)
        x = resample_poly(x, 16000 // g, fs // g)
    raw = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
    raw.write((x.clip(-1, 1) * 32767).astype("<i2").tobytes())
    raw.close()
    cmd = [CLI, "--live", raw.name, str(args.speed)]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)


def pump_out():
    while True:
        d = os.read(p.stdout.fileno(), 4096)
        if not d:
            break
        os.write(master, d)


threading.Thread(target=pump_out, daemon=True).start()
while True:
    try:
        d = os.read(master, 4096)
    except OSError:
        break
    if not d:
        break
    p.stdin.write(d)
