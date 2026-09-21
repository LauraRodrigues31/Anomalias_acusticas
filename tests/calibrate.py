"""Calibração ao vivo do firmware de produção (esp32dev) SEM regravar: usa os comandos de serial
GATE/THR/VOTE/MON/STATS (docs/serial_protocol.md).

Coletar (uma vez por situação; deixe o som tocar/acontecer durante os N segundos):
  python tests/calibrate.py --port /dev/ttyUSB0 --label silencio   --seconds 10
  python tests/calibrate.py --port /dev/ttyUSB0 --label alarme     --seconds 20   # celular a 30-50 cm
  python tests/calibrate.py --port /dev/ttyUSB0 --label fala|despertador|palma --seconds 10
Sugerir (usa tudo o que foi coletado; --apply envia GATE/THR/VOTE ao dispositivo, só em RAM):
  python tests/calibrate.py --suggest [--port /dev/ttyUSB0 --apply]

Sessão guiada (recomendada; um rótulo por vez, 20 s cada, grava docs/results/calibracao_<data>.csv, NÃO versionado):
  python tests/calibrate.py --port /dev/ttyUSB0 --sessao [--segundos 20] [--apply]
  python tests/calibrate.py --analisar docs/results/calibracao_<data>.csv     # refaz a análise sem dispositivo

Durante a coleta o gate fica em -120 dBFS (para ver a probabilidade de todas as janelas) e é restaurado
no fim. As amostras ficam em data/processed/calibration/ (fora do git). Nada aqui muda o modelo.
"""
import argparse
import glob
import json
import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ml import config as C

LABELS = ["silencio", "fala", "alarme", "despertador", "palma",
          "palma_mesa", "sirene", "toque", "alarme_fumaca"]
SESSAO = [  # (rótulo, instrução)
    ("silencio", "fique em SILENCIO (sem tocar nada)"),
    ("fala", "FALE normalmente (ou toque uma fala/podcast)"),
    ("palma_mesa", "bata PALMAS e batidas na MESA, teclado, chaves"),
    ("sirene", "toque a SIRENE (celular/YouTube), no volume da demo"),
    ("despertador", "toque o DESPERTADOR do celular"),
    ("toque", "toque o TOQUE DE LIGAÇÃO do celular"),
    ("alarme_fumaca", "toque o ALARME DE FUMAÇA (a 30-50 cm do microfone)"),
]
ALARME = "alarme_fumaca"
THR_SESSAO = [0.90, 0.95, 0.98, 0.99, 0.995]
VOTE_SESSAO = [(6, 8), (7, 8), (8, 8), (10, 12), (12, 16)]
COOLDOWN_MS = C.COOLDOWN_MS
OUT = os.path.join(C.ROOT, "data", "processed", "calibration")
THR_GRID = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98, 0.99]
VOTE_GRID = [(3, 5), (2, 3), (4, 5), (5, 8), (6, 8)]          # votos rápidos (<= 8 janelas = 256 ms)
VOTE_GRID_SLOW = [(8, 12), (10, 16)]                          # só se nenhum rápido evitar falsos alertas


# --------------------------------------------------------------------------- serial
class Device:
    def __init__(self, port, baud=921600, settle=2.0):
        import serial
        self.ser = serial.Serial(port, baud, timeout=0.2)
        time.sleep(settle)                 # abrir a porta reinicia o ESP32; espera o boot
        self.ser.reset_input_buffer()
        self.buf = b""

    def send(self, line):
        self.ser.write((line + "\n").encode())

    def lines(self, timeout):
        """Gera linhas recebidas durante `timeout` segundos."""
        t_end = time.time() + timeout
        while time.time() < t_end:
            self.buf += self.ser.read(4096)
            while b"\n" in self.buf:
                ln, self.buf = self.buf.split(b"\n", 1)
                yield ln.decode(errors="replace").strip()

    def command(self, line, timeout=2.0):
        """Envia um comando e devolve a resposta OK/ERR (ou None)."""
        self.send(line)
        for ln in self.lines(timeout):
            if ln.startswith(("OK", "ERR")):
                return ln
        return None

    def params(self, timeout=6.0):
        """STATS -> linha P,gate,thr,n,m,mon."""
        self.send("STATS")
        for ln in self.lines(timeout):
            if ln.startswith("P,"):
                g, t, n, m, mon = ln.split(",")[1:6]
                return dict(gate=float(g), thr=float(t), n=int(n), m=int(m), mon=int(mon))
        return None

    def close(self):
        self.ser.close()


def pct(v, q):
    return float(np.percentile(v, q)) if len(v) else float("nan")


def collect(a):
    dev = Device(a.port, a.baud, a.settle)
    orig = dev.params()
    if orig is None:
        dev.close()
        sys.exit("Sem resposta ao STATS: confira a porta e se o firmware é o esp32dev (produção).")
    print(f"parâmetros atuais do dispositivo: gate={orig['gate']} dBFS thr={orig['thr']} voto={orig['n']} de {orig['m']}")
    rec = []
    try:
        print("GATE -120 ->", dev.command("GATE -120"))
        print("MON 1 ->", dev.command("MON 1"))
        print(f"coletando '{a.label}' por {a.seconds} s ...")
        for ln in dev.lines(a.seconds):
            if ln.startswith("M,"):
                p = ln.split(",")
                try:
                    rec.append((int(p[1]), float(p[2]), float(p[3])))
                except (ValueError, IndexError):
                    pass            # linha truncada
    finally:                         # sempre restaura o dispositivo
        dev.command("MON 0")
        dev.command(f"GATE {orig['gate']}")
        dev.close()
    if len(rec) < 20:
        sys.exit(f"Poucas janelas ({len(rec)}). O firmware está capturando? (autoteste, fiação)")
    rec.sort()
    wins = np.array([r[0] for r in rec])
    gaps = int((np.diff(wins) > 1).sum())
    rms = np.array([r[1] for r in rec])
    prob = np.array([r[2] for r in rec])
    ref_gate, thr = orig["gate"], orig["thr"]
    above = rms >= ref_gate
    print(f"\n== {a.label}: {len(rec)} janelas ({gaps} lacunas de janelas perdidas no monitor)")
    print(f"rms_db  p50={pct(rms,50):7.1f}  p95={pct(rms,95):7.1f}  max={rms.max():7.1f}   (gate atual {ref_gate})")
    print(f"prob    p50={pct(prob,50):7.3f}  p95={pct(prob,95):7.3f}  max={prob.max():7.3f}   (todas as janelas)")
    if above.any():
        pa = prob[above]
        print(f"acima do gate: {100*above.mean():.0f}% das janelas | prob p50={pct(pa,50):.3f} p95={pct(pa,95):.3f} max={pa.max():.3f} "
              f"| {100*(pa >= thr).mean():.0f}% delas >= limiar {thr}")
    else:
        print("nenhuma janela acima do gate atual")
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{a.label}_{time.strftime('%Y%m%d-%H%M%S')}.json")
    json.dump(dict(label=a.label, gate_ref=ref_gate, thr_ref=thr, vote_ref=[orig["n"], orig["m"]],
                   win=wins.tolist(), rms_db=rms.tolist(), prob=prob.tolist()), open(path, "w"))
    print("salvo:", os.path.relpath(path, C.ROOT))


# --------------------------------------------------------------------------- sugestão
def load_all():
    data = {}
    for p in sorted(glob.glob(os.path.join(OUT, "*.json"))):
        d = json.load(open(p))
        cur = data.setdefault(d["label"], dict(rms=[], prob=[], seqs=[]))
        cur["rms"] += d["rms_db"]
        cur["prob"] += d["prob"]
        cur["seqs"].append((np.array(d["rms_db"]), np.array(d["prob"])))
        cur["ref"] = dict(gate=d["gate_ref"], thr=d["thr_ref"], vote=d["vote_ref"])
    return data


def alert_state(pos, n, m):
    """Por janela: True se a soma das últimas m posições >= n (mesma regra do firmware)."""
    cs = np.cumsum(pos.astype(np.int32))
    prev = np.r_[np.zeros(m, np.int32), cs][: len(cs)]
    return (cs - prev) >= n


def evaluate(seqs, gate, thr, n, m):
    """Janelas em estado de alerta e nº de sequências com algum alerta, sobre as sequências coletadas."""
    tot = alerting = seq_alert = 0
    for rms, prob in seqs:
        st = alert_state((rms >= gate) & (prob >= thr), n, m)
        tot += len(st)
        alerting += int(st.sum())
        seq_alert += int(st.any())
    return alerting / max(tot, 1), seq_alert, len(seqs)


def suggest(a):
    data = load_all()
    for need in ("silencio", "alarme"):
        if need not in data:
            sys.exit(f"Faltam amostras de '{need}'. Colete com --label {need}.")
    sil_rms = np.array(data["silencio"]["rms"])
    al_rms = np.array(data["alarme"]["rms"])
    sil_p95, al_p05 = pct(sil_rms, 95), pct(al_rms, 5)
    # o alarme tem pausas entre bipes (janelas de silêncio): use as janelas "altas" do alarme
    al_loud = pct(al_rms, 50)
    gate = min(sil_p95 + 6.0, al_loud - 15.0)
    warn = []
    if gate < sil_p95 + 1.0:
        gate = sil_p95 + 3.0
        warn.append("o alarme fica perto do ruído da sala: pouca margem para o gate (aproxime o celular ou aumente o ganho)")
    gate = float(np.clip(round(gate, 1), -90.0, -20.0))
    print(f"GATE: silêncio p95={sil_p95:.1f} dBFS, alarme p50={al_loud:.1f} dBFS -> gate sugerido {gate} dBFS")

    negs = {k: v for k, v in data.items() if k != "alarme"}
    best = None
    for grid in (VOTE_GRID, VOTE_GRID + VOTE_GRID_SLOW):
        for thr in THR_GRID:
            for n, m in grid:
                neg_alert = sum(evaluate(v["seqs"], gate, thr, n, m)[1] for v in negs.values())
                neg_frac = sum(evaluate(v["seqs"], gate, thr, n, m)[0] for v in negs.values())
                cov, sa, ns = evaluate(data["alarme"]["seqs"], gate, thr, n, m)
                # sem falso alerta > alarme sempre detectado > menos janelas negativas em alerta
                # > cobertura do alarme (degraus de 5%) > voto mais rápido (menor n) > limiar maior
                key = (neg_alert == 0, sa == ns, -neg_frac, round(cov * 20) / 20, -n, thr)
                if best is None or key > best[0]:
                    best = (key, thr, n, m, neg_alert, cov, sa, ns)
        if best[0][0] and best[0][1]:
            break          # já há combinação rápida sem falso alerta e que detecta o alarme
    _, thr, n, m, neg_alert, cov, sa, ns = best
    print(f"THR/VOTE: limiar {thr}, voto {n} de {m} -> alarme em alerta em {100*cov:.0f}% das janelas "
          f"({sa}/{ns} coletas com alerta); situações negativas com alerta: {neg_alert} de {len(negs)} "
          f"({', '.join(sorted(negs))})")
    if neg_alert:
        warn.append("nenhuma combinação evitou todos os falsos alertas nas suas coletas; o modelo (4 features de uma janela) "
                    "não separa bem esses sons: reporte isso em vez de forçar o limiar")
    if sa < ns:
        warn.append("o alarme não disparou em todas as coletas com esses parâmetros")
    for w in warn:
        print("AVISO:", w)
    cmds = [f"GATE {gate}", f"THR {thr}", f"VOTE {n} {m}"]
    print("comandos sugeridos (só RAM; um reset volta ao padrão):", " | ".join(cmds))
    if a.apply:
        if not a.port:
            sys.exit("--apply exige --port")
        dev = Device(a.port, a.baud, a.settle)
        for c in cmds:
            print(c, "->", dev.command(c))
        print("parâmetros agora:", dev.params())
        dev.close()
    print("Para tornar permanente: ajuste ml/config.py/train (limiar e N/M vêm do treino) e regrave; "
          "o gate vem de RMS_GATE_DB em ml/config.py + `python -m ml.gen_headers`.")


# --------------------------------------------------------------------------- sessão guiada
def contar_alertas(win, rms, prob, gate, thr, n, m):
    """Réplica da regra do firmware: n de m janelas positivas + cooldown (tempo = janela x 32 ms)."""
    pos = (rms >= gate) & (prob >= thr)
    hist, last, alerts = [], None, 0
    for w, p in zip(win, pos):
        hist.append(bool(p))
        if len(hist) > m:
            hist.pop(0)
        t = int(w) * 32
        if sum(hist) >= n and (last is None or t - last >= COOLDOWN_MS):
            alerts += 1
            last = t
    return alerts


def max_soma(win, rms, prob, gate, thr, m):
    """Maior nº de janelas positivas em qualquer trecho de m janelas (quão perto a coleta chegou de alertar)."""
    pos = ((rms >= gate) & (prob >= thr)).astype(np.int32)
    if len(pos) == 0:
        return 0
    cs = np.r_[0, np.cumsum(pos)]
    k = min(m, len(pos))
    return int((cs[k:] - cs[:-k]).max()) if len(pos) >= k else int(cs[-1])


def coletar_janelas(dev, seconds):
    """MON 1, lê linhas M por `seconds` s, MON 0. Retorna lista (janela, rms_db, prob, pos) sem repetidas."""
    dev.command("MON 1")
    dev.ser.reset_input_buffer()
    dev.buf = b""
    vistos, rec = set(), []
    for ln in dev.lines(seconds):
        if ln.startswith("M,"):
            p = ln.split(",")
            try:
                w = int(p[1])
                if w in vistos:
                    continue
                vistos.add(w)
                rec.append((w, float(p[2]), float(p[3]), int(p[4])))
            except (ValueError, IndexError):
                pass                      # linha truncada
    dev.command("MON 0")
    dev.ser.reset_input_buffer()
    dev.buf = b""
    return sorted(rec)


CSV_COLS = ["rotulo", "janela", "t_s", "rms_db", "prob", "pos", "acima_gate", "gate_ref", "thr_ref"]


def ler_csv(path):
    import csv
    dados = {}
    gate = thr = None
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            d = dados.setdefault(r["rotulo"], dict(win=[], rms=[], prob=[]))
            d["win"].append(int(r["janela"]))
            d["rms"].append(float(r["rms_db"]))
            d["prob"].append(float(r["prob"]))
            gate, thr = float(r["gate_ref"]), float(r["thr_ref"])
    return {k: dict(win=np.array(v["win"]), rms=np.array(v["rms"]), prob=np.array(v["prob"])) for k, v in dados.items()}, gate, thr


def analisar(dados, gate, thr_ref=None):
    """Imprime as tabelas e a recomendação. Retorna (thr, n, m) recomendado se separar, senão None."""
    ordem = [l for l, _ in SESSAO if l in dados] + [l for l in dados if l not in [x for x, _ in SESSAO]]
    print(f"\n=== ANÁLISE (gate de referência {gate} dBFS; cooldown {COOLDOWN_MS/1000:.0f} s; "
          f"limiar do dispositivo na coleta {thr_ref}) ===")
    print("\nProbabilidade por rótulo (só janelas ACIMA do gate)")
    print(f"{'rótulo':14s} {'janelas':>8s} {'acima gate':>12s} {'prob p50':>9s} {'p95':>7s} {'máx':>7s} {'>=0,90':>8s}")
    stat = {}
    for l in ordem:
        d = dados[l]
        ab = d["rms"] >= gate
        pa = d["prob"][ab]
        stat[l] = pa
        if len(pa):
            print(f"{l:14s} {len(d['win']):8d} {int(ab.sum()):6d} ({100*ab.mean():3.0f}%) {pct(pa,50):9.3f} {pct(pa,95):7.3f} "
                  f"{pa.max():7.3f} {100*(pa>=0.9).mean():7.0f}%")
        else:
            print(f"{l:14s} {len(d['win']):8d} {0:6d} ({0:3d}%) {'-':>9s} {'-':>7s} {'-':>7s} {'-':>8s}")

    print("\nALERTAS que teriam disparado na coleta (mesma regra do firmware: n de m + cooldown)")
    abrev = {l: l[:9] for l in ordem}
    print(f"{'THR':>6s} {'VOTE':>7s} | " + " ".join(f"{abrev[l]:>9s}" for l in ordem) + " | falsos  ")
    cand = []
    for thr in THR_SESSAO:
        for n, m in VOTE_SESSAO:
            cont = {l: contar_alertas(dados[l]["win"], dados[l]["rms"], dados[l]["prob"], gate, thr, n, m) for l in ordem}
            falsos = sum(v for l, v in cont.items() if l != ALARME)
            rot_falsos = sum(1 for l, v in cont.items() if l != ALARME and v > 0)
            det = cont.get(ALARME, 0)
            marca = " <- separa" if det >= 1 and falsos == 0 else ""
            print(f"{thr:6.3f} {n:3d}/{m:<3d} | " + " ".join(f"{cont[l]:9d}" for l in ordem) + f" | {falsos:5d}{marca}")
            # margem contra falso alerta: quão longe do voto n o pior rótulo negativo ficou (1 = nunca positivo)
            negs = [l for l in ordem if l != ALARME]
            worst = max((max_soma(dados[l]["win"], dados[l]["rms"], dados[l]["prob"], gate, thr, m) for l in negs), default=0)
            margem = (n - worst) / n
            cand.append((thr, n, m, det, falsos, rot_falsos, cont, margem))

    if ALARME not in dados:
        print(f"\nSem coleta '{ALARME}': não dá para recomendar.")
        return None
    ok = [c for c in cand if c[3] >= 1]
    print("\n=== RECOMENDAÇÃO ===")
    if not ok:
        print("O alarme de fumaça NÃO foi detectado em nenhuma combinação (nem 0,90 com 6 de 8). Causas prováveis: "
              "gate alto demais para o volume do celular, alarme muito baixo, canal/ganho do microfone, "
              "ou o som tocado pelo alto-falante do celular é muito diferente do treino. Veja a linha '"
              f"{ALARME}' acima: janelas acima do gate e prob.")
        return None
    # menos falsos > menos rótulos com falso > margem contra falso alerta SUFICIENTE (o pior som negativo chega a
    # no máx. metade do voto) > alarme detectado com folga (>= 80% do melhor nº de alertas) > voto mais rápido
    # (menor n) > limiar mais BAIXO (mais sensível ao alarme real, que tende a ter prob menor que o de laboratório)
    melhor_det = max(c[3] for c in ok)
    ok.sort(key=lambda c: (c[4], c[5], -(c[7] >= 0.5), -(c[3] >= 0.8 * melhor_det), c[1], c[0]))
    thr, n, m, det, falsos, rot_f, cont, margem_neg = ok[0]
    pal = stat.get(ALARME, np.array([]))
    if falsos == 0:
        print(f"SEPARA: THR {thr} com VOTE {n} de {m} detecta o alarme ({det} alerta(s) em {len(dados[ALARME]['win'])*32/1000:.0f} s) "
              f"e não dispara em nenhum outro rótulo coletado (margem contra falso alerta {100*margem_neg:.0f}%: o pior som negativo chegou a "
              f"{round((1-margem_neg)*n)} de {n} votos).")
        margem = [c for c in ok if c[4] == 0]
        print(f"({len(margem)} de {len(cand)} combinações separam; a escolhida tem margem suficiente contra falso alerta, mantém o alarme com folga e é a mais sensível.)")
        print("Cuidado: só vale para estes sons, volumes e posição do celular; teste de novo ao vivo antes de confiar.")
        res = (thr, n, m)
    else:
        print(f"NENHUMA combinação separa o alarme de fumaça dos outros sons: a melhor ainda dispara {falsos} alerta(s) "
              f"falso(s) em {rot_f} rótulo(s) ({', '.join(l for l, v in cont.items() if l != ALARME and v > 0)}) "
              f"[THR {thr}, VOTE {n} de {m}; alarme detectado {det}x].")
        print("Por quê: as probabilidades se SOBREPÕEM. O modelo só vê 4 números de UMA janela (centroide, razão 2-4 kHz, "
              "picosidade e frequência do pico); sirene, despertador e toque também são tons agudos, então recebem "
              "probabilidade tão alta quanto o alarme e nenhum limiar ou voto os separa sem perder o alarme:")
        if len(pal):
            p10 = pct(pal, 10)
            print(f"  alarme_fumaca: prob p10={p10:.3f} p50={pct(pal,50):.3f}")
            for l in ordem:
                if l == ALARME or not len(stat[l]):
                    continue
                sob = 100 * float((stat[l] >= p10).mean())
                print(f"  {l:14s}: p95={pct(stat[l],95):.3f} máx={stat[l].max():.3f} | {sob:3.0f}% das janelas acima do gate têm prob >= {p10:.3f} (p10 do alarme)")
        print("Opções honestas: (a) aceitar disparos nesses sons e reportar; (b) usar o combo acima só como 'menos ruim'; "
              "(c) melhorar o MODELO (features com informação temporal: padrão 3 bipes + pausa; e reincluir esses sons "
              "gravados no treino como negativos), o que exige retreino e nova avaliação, não um ajuste de limiar.")
        res = None
    if falsos:
        print("\nCombinação 'menos ruim' (NÃO separa; --apply não a aplica). Se mesmo assim quiser testá-la ao vivo, envie pelo monitor serial:")
    else:
        print("\nPara aplicar ao vivo (só RAM; envie pelo monitor serial com Enter, ou use --apply):")
    print(f"  THR {thr}")
    print(f"  VOTE {n} {m}")
    return res


def sessao(a):
    import csv
    dev = Device(a.port, a.baud, a.settle)
    orig = dev.params()
    if orig is None:
        dev.close()
        sys.exit("Sem resposta ao STATS: confira a porta e se o firmware é o esp32dev (produção).")
    print(f"parâmetros atuais: gate={orig['gate']} dBFS thr={orig['thr']} voto={orig['n']} de {orig['m']}")
    print("Durante a sessão o gate fica em -120 dBFS e é restaurado no fim. Ctrl+C interrompe (o que já foi coletado é mantido).")
    os.makedirs(os.path.join(C.ROOT, "docs", "results"), exist_ok=True)
    path = os.path.join(C.ROOT, "docs", "results", f"calibracao_{time.strftime('%Y%m%d-%H%M%S')}.csv")
    with open(path, "w", newline="") as f:
        csv.writer(f).writerow(CSV_COLS)
    dados = {}
    try:
        print("GATE -120 ->", dev.command("GATE -120"))
        for i, (lab, instr) in enumerate(SESSAO, 1):
            try:
                input(f"\n[{i}/{len(SESSAO)}] {lab}: {instr}.\n   Aperte Enter e mantenha o som por {a.segundos:.0f} s ... ")
            except EOFError:
                pass
            print(f"   coletando '{lab}' ...")
            rec = coletar_janelas(dev, a.segundos)
            if len(rec) < 20:
                print(f"   AVISO: só {len(rec)} janelas; o firmware está capturando? (pulando '{lab}')")
                continue
            with open(path, "a", newline="") as f:
                w = csv.writer(f)
                for (jn, rms, prob, pos) in rec:
                    w.writerow([lab, jn, f"{jn*0.032:.3f}", rms, prob, pos, int(rms >= orig["gate"]), orig["gate"], orig["thr"]])
            r = np.array([x[1] for x in rec]); pr = np.array([x[2] for x in rec])
            print(f"   {len(rec)} janelas | rms p50={pct(r,50):.1f} máx={r.max():.1f} dBFS | prob p95={pct(pr,95):.3f} máx={pr.max():.3f}")
            dados[lab] = dict(win=np.array([x[0] for x in rec]), rms=r, prob=pr)
    except KeyboardInterrupt:
        print("\ninterrompido.")
    finally:
        dev.command("MON 0")
        print("restaurando GATE ->", dev.command(f"GATE {orig['gate']}"))
    print("\ndados salvos em", os.path.relpath(path, C.ROOT), "(não versionado)")
    rec_ = analisar(dados, orig["gate"], orig["thr"]) if dados else None
    if a.apply and rec_:
        thr, n, m = rec_
        print("\n--apply:", dev.command(f"THR {thr}"), "|", dev.command(f"VOTE {n} {m}"), "| agora:", dev.params())
    elif a.apply:
        print("\n--apply NÃO aplicado: nenhuma combinação separa o alarme dos outros sons.")
    dev.close()



def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--label", choices=LABELS)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--settle", type=float, default=2.0, help="espera após abrir a porta (o ESP32 reinicia)")
    ap.add_argument("--suggest", action="store_true")
    ap.add_argument("--sessao", action="store_true", help="sessão guiada com todos os rótulos (CSV em docs/results/)")
    ap.add_argument("--segundos", type=float, default=20.0, help="duração de cada coleta da --sessao")
    ap.add_argument("--analisar", metavar="CSV", help="reanalisa um docs/results/calibracao_*.csv (sem dispositivo)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.analisar:
        dados, gate, thr = ler_csv(a.analisar)
        analisar(dados, gate, thr)
        return
    if a.sessao:
        if not a.port:
            ap.error("--sessao exige --port")
        return sessao(a)
    if a.suggest:
        return suggest(a)
    if not (a.port and a.label):
        ap.error("informe --port e --label (ou use --suggest)")
    collect(a)


if __name__ == "__main__":
    main()
