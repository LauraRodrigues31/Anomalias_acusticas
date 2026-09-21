"""Dispositivo serial FALSO para testar o lado do host de `run_test.py --target serial` sem placa.
Cria um pty e liga-o ao dsp_cli nativo (mesmo protocolo START/W/A/S/DONE). NÃO mede nada do ESP32.
Uso: python tests/fake_esp32.py   (imprime o caminho do pty; deixe rodando e use --target serial:<caminho>)"""
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
p = subprocess.Popen([CLI], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)


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
