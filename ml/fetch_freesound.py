"""Baixa clipes de alarme de fumaça pela API OFICIAL do Freesound (https://freesound.org/docs/api/).

- Token lido de FREESOUND_API_KEY (nunca versionado). Sem a variável: avisa e sai sem erro.
- Busca "smoke alarm" e "smoke detector"; mantém só licenças CC0 e CC-BY (Attribution).
- Baixa o PREVIEW (mp3 hq): o download do arquivo original exige OAuth2, o preview só o token.
  Converte para WAV 16 kHz mono em data/raw/smoke_real/ e grava SOURCES.csv (id, autor, licença, URL).
- Respeita o limite oficial (60 req/min): pausa entre chamadas.

Uso: FREESOUND_API_KEY=... python -m ml.fetch_freesound [--max 40]
"""
import argparse
import csv
import io
import os
import sys
import time
import numpy as np
import requests
import soundfile as sf
from scipy.signal import resample_poly
from ml import config as C

API = "https://freesound.org/apiv2"
OUT = os.path.join(C.ROOT, "data", "raw", "smoke_real")
QUERIES = ["smoke alarm", "smoke detector"]
LICENSES = ["Creative Commons 0", "Attribution"]     # CC0 e CC-BY
FIELDS = "id,name,username,license,url,duration,previews"
PAUSE_S = 1.2   # < 60 req/min


def get(session, url, key, **params):
    """GET com o token no cabeçalho oficial; uma repetição em caso de 429."""
    for attempt in range(3):
        r = session.get(url, params=params, headers={"Authorization": f"Token {key}"}, timeout=30)
        if r.status_code == 429:
            time.sleep(30)
            continue
        r.raise_for_status()
        time.sleep(PAUSE_S)
        return r
    raise RuntimeError("limite de requisições (429) persistente")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=40)
    a = ap.parse_args()
    key = os.environ.get("FREESOUND_API_KEY")
    if not key:
        print("AVISO: variável FREESOUND_API_KEY não definida; pulando o download do Freesound.\n"
              "       Crie uma chave em https://freesound.org/apiv2/apply e rode: "
              "FREESOUND_API_KEY=... python -m ml.fetch_freesound", file=sys.stderr)
        return 0
    os.makedirs(OUT, exist_ok=True)
    lic_filter = " OR ".join(f'"{l}"' for l in LICENSES)
    s = requests.Session()
    found = {}
    rows = []
    try:
        for q in QUERIES:
            r = get(s, f"{API}/search/text/", key, query=q, filter=f"license:({lic_filter}) duration:[0.5 TO 30]",
                    fields=FIELDS, page_size=50)
            for it in r.json().get("results", []):
                if it["license"] in LICENSES and it["id"] not in found:
                    found[it["id"]] = it
        print(f"{len(found)} candidatos (CC0/CC-BY)")
        rows = []
        for sid, it in list(found.items())[: a.max]:
            url = it["previews"]["preview-hq-mp3"]
            r = get(s, url, key)
            try:
                x, fs = sf.read(io.BytesIO(r.content), dtype="float32", always_2d=True)
            except Exception as e:  # mp3 sem suporte no libsndfile instalado
                print(f"  {sid}: falha ao decodificar ({e}); pulando")
                continue
            x = x.mean(axis=1)
            if fs != C.FS:
                x = resample_poly(x, C.FS, fs).astype(np.float32)
            fn = f"fs_{sid}.wav"
            sf.write(os.path.join(OUT, fn), x, C.FS, subtype="PCM_16")
            rows.append(dict(id=sid, file=fn, author=it["username"], license=it["license"], url=it["url"],
                             name=it["name"], duration_s=round(it["duration"], 2),
                             note="preview mp3 hq convertido para 16 kHz mono"))
            print(f"  baixado {fn} ({it['license']}, {it['username']})")
    except Exception as e:
        print(f"ERRO na API do Freesound: {e}", file=sys.stderr)
    if rows:
        with open(os.path.join(OUT, "SOURCES.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"{len(rows)} clipes gravados em {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
