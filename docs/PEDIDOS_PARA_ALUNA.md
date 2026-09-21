# Pedidos para a aluna

1. **Chave do Freesound (opcional, mas recomendada):** crie em https://freesound.org/apiv2/apply e rode `FREESOUND_API_KEY=... python -m ml.fetch_freesound` (não cole a chave em nenhum arquivo do repositório).
2. **Clipes reais baixados por você:** coloque em `data/raw/smoke_real_manual/` (anote autor e licença em `SOURCES.csv` na mesma pasta). Eles serão usados **apenas como teste real**, nunca no treino.
3. **Áudio da demo:** `data/raw/demo/alarm_demo.wav` (fica fora de treino/validação/teste).
4. Se, somando API e manual, houver **menos de 10 clipes reais**, eu aviso antes de decidir como reportar.
