"""Curadoria dos clipes reais baixados do Freesound (limpeza de ruído de rótulo, sem ouvir os áudios).

Exclui, gravando data/raw/smoke_real/EXCLUDED.csv (os arquivos ficam onde estão; build_dataset os ignora):
  (a) título/metadata claramente não relacionado a alarme de fumaça (lista manual abaixo, por id);
  (b) energia na banda 2-4 kHz desprezível (mediana de band_ratio das janelas ativas < 0.3): não é
      um alarme de piezo; provavelmente locução/ruído com título enganoso;
  (c) nível máximo abaixo do gate (rms_db < RMS_GATE_DB em todas as janelas): não pode disparar.
LIMITAÇÃO: (b) e (c) usam as próprias features; a aluna deve conferir os excluídos OUVINDO.
Uso: python -m ml.curate_real
"""
import os
import numpy as np
import pandas as pd
import soundfile as sf
from ml import config as C
from ml import features as F

D = os.path.join(C.ROOT, "data", "raw", "smoke_real")
TITLE_UNRELATED = {  # id -> motivo (por título)
    385946: "título: explosões/granadas", 692501: "título: 'Am (Americium)' (elemento químico)",
    253546: "título: 'SCORE COUNT' (efeito de jogo)", 802099: "título: 'PSA - Fire Safety Check' (locução)",
    336898: "título: 'siren-02-kitchen' (sirene, não alarme de fumaça)",
    620071: "título: 'Breaking Plastic Smoke Alarm' (quebra de plástico)",
}


def main():
    src = pd.read_csv(os.path.join(D, "SOURCES.csv"))
    rows = []
    for _, r in src.iterrows():
        x, _ = sf.read(os.path.join(D, r.file), dtype="float32")
        w = F.clip_features((np.clip(x, -1, 1) * 32767).astype(np.int16))
        db = np.array([q["rms_db"] for q in w]) if w else np.array([-200.0])
        act = [q for q in w if q["rms_db"] >= C.RMS_GATE_DB]
        med = float(np.median([q["band_ratio"] for q in act])) if act else 0.0
        reason = None
        if int(r.id) in TITLE_UNRELATED:
            reason = TITLE_UNRELATED[int(r.id)]
        elif db.max() < C.RMS_GATE_DB:
            reason = f"nível máximo {db.max():.1f} dBFS abaixo do gate"
        elif med < 0.3:
            reason = f"band_ratio mediano {med:.2f} < 0.3 (sem tom na banda 2-4 kHz)"
        if reason:
            rows.append(dict(id=r.id, file=r.file, name=r["name"], reason=reason))
    pd.DataFrame(rows, columns=["id", "file", "name", "reason"]).to_csv(os.path.join(D, "EXCLUDED.csv"), index=False)
    print(f"{len(src)} baixados, {len(rows)} excluídos, {len(src) - len(rows)} mantidos")
    for r in rows:
        print(f"  - {r['file']}: {r['reason']}")


if __name__ == "__main__":
    main()
