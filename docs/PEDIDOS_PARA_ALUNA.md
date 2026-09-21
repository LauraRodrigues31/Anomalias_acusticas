# Pedidos para a aluna

1. **Conferir OUVINDO os clipes reais do Freesound.** `python -m ml.fetch_freesound` baixou 32 clipes (CC0/CC-BY, ver `data/raw/smoke_real/SOURCES.csv`). Como não posso ouvir, `ml/curate_real.py` excluiu 12 por critérios objetivos (título sem relação com alarme, sem tom em 2–4 kHz, ou nível abaixo do gate); veja `data/raw/smoke_real/EXCLUDED.csv`. Ouça os excluídos e os mantidos: se algum excluído for alarme de verdade (ou algum mantido não for), me diga o id. Ficaram 20 clipes.
2. **Clipes reais baixados por você** (opcional, reforça o teste): coloque em `data/raw/smoke_real_manual/` (anote autor e licença em `SOURCES.csv` na mesma pasta). Serão **apenas teste real**, nunca treino/validação.
3. **Áudio da demo:** `data/raw/demo/alarm_demo.wav` (fora de treino/validação/teste; só `--demo-clip`).
4. **Atenção ao relatório:** os positivos reais são poucos (20 clipes de ~15 autores, divididos por autor). O recall "real" no teste vem de poucos clipes e tem incerteza grande; o relatório deve dizer isso.
5. **Atribuição CC-BY:** ao publicar o relatório, cite autor/URL dos clipes CC-BY usados (`SOURCES.csv`).
