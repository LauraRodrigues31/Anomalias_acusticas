# Dados

**Nenhum áudio é versionado** (`data/raw/` e `data/processed/` estão no `.gitignore`). Aqui ficam só as fontes, licenças e como reproduzir.

## Fontes

| Uso | Fonte | Licença | Como obter |
|---|---|---|---|
| Positivo sintético | Hugging Face `ShantyCam/audiodet-synth-smoke` (250 clipes, 16 kHz, 8 s, padrão T3) | CC-BY-4.0 | `huggingface_hub.snapshot_download(..., repo_type="dataset", local_dir="data/raw/hf_synth_smoke")` |
| Positivo sintético | Gerador próprio `ml/gen_smoke_alarm.py` (semente fixa, T3/T4/contínuo, harmônicos, deriva, reverberação) | código do projeto | gerado em `ml/build_dataset.py` |
| Positivo real (API) | Freesound, API oficial, "smoke alarm"/"smoke detector", só CC0 e CC-BY | por clipe, em `data/raw/smoke_real/SOURCES.csv` | `FREESOUND_API_KEY=... python -m ml.fetch_freesound` |
| Positivo real **manual** | baixados pela aluna em `data/raw/smoke_real_manual/` | por clipe (anotar em `SOURCES.csv` da pasta) | manual. **Só teste real** |
| Negativos | ESC-50 (2000 clipes, 5 s, 50 classes; 44,1 kHz → 16 kHz) | ver `data/raw/ESC-50/LICENSE` (o conjunto todo é CC BY-NC 3.0, uso acadêmico; o subconjunto ESC-10 é CC BY 3.0) | `git clone --depth 1 https://github.com/karolpiczak/ESC-50 data/raw/ESC-50` |
| Fala | `mini_speech_commands` (excerto do Speech Commands, TensorFlow; 8 palavras de 1 s, muitos locutores) | **confirmar**: o README do excerto não traz a licença e remete ao dataset original (Speech Commands) | `curl -O http://storage.googleapis.com/download.tensorflow.org/data/mini_speech_commands.zip` e descompactar em `data/raw/` |
| Ruído de sala | branco/rosa/marrom sintéticos + classes de ambiente do ESC-50 | — | gerado em `build_dataset.py` |
| Demo | `data/raw/demo/alarm_demo.wav` (se existir) | — | **fora de treino, validação e teste**; só `--demo-clip` |

Limitação: o ESC-50 não tem fala contínua; usamos 5 palavras de `mini_speech_commands` concatenadas (~5 s) por clipe de fala, o que é fala **isolada**, não conversa.

## Reproduzir

```bash
source .venv/bin/activate
# baixe as fontes acima em data/raw/, depois:
python -m ml.build_dataset          # ~1 min; grava data/processed/
```

## Regras

- **Split por clipe** (nunca por janela), semente fixa: ESC-50 pelos folds oficiais (1–3 treino, 4 validação, 5 teste); sintéticos 70/15/15; fala dividida **por locutor**; ruído sintético 70/15/15; Freesound 70/15/15.
- **Real manual** → sempre teste. **Demo** → fora de tudo.
- **Rotulagem de janelas:** positiva se `rms_db ≥ −50 dBFS` **e** `band_power` a menos de 20 dB do máximo do clipe; pausas entre bipes são **excluídas**. Negativa se `rms_db ≥ −50`; abaixo do gate, excluída.
- **Augmentation só no treino** (ganho −40..−5 dBFS de pico, ruído de fundo SNR 0–30 dB, deslocamento, resposta de alto-falante, reverberação, alarme sobre fala, clipping leve). Variantes herdam o clip do original.
- **Negativos difíceis** (marcados nos manifestos): `clock_alarm`, `siren`, `car_horn`, `church_bells`, `door_wood_knock`, `keyboard_typing`, `mouse_click`, `clapping`, `glass_breaking`, `crying_baby`.

## Situação atual dos positivos reais (Freesound, API oficial)

32 clipes baixados (19 CC0, 13 CC-BY; o *preview* mp3 convertido para 16 kHz mono). `ml/curate_real.py` excluiu 12 por critérios objetivos (`EXCLUDED.csv`); **20 clipes** ficam (14 treino / 3 validação / 3 teste, divididos **por autor** para não vazar séries quase duplicadas). São poucos: as métricas "positivo real" têm incerteza grande. Não há clipes em `smoke_real_manual/` (teste real) nem `alarm_demo.wav`. A chave fica em `.env` (ignorado pelo git; modelo em `.env.example`).
