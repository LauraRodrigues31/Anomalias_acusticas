# Decisões de projeto

As decisões fechadas estão na seção 2 do `CLAUDE.md`. Este arquivo registra decisões tomadas durante a implementação e qualquer desvio (com justificativa).

| # | Decisão | Justificativa |
|---|---|---|
| D0 | Ambiente Python em `.venv/` (ignorado pelo git), PlatformIO instalado via pip nele. | `pio` não estava instalado no sistema. |
| D1 | `firmware/lib/dsp/features.*` chama-se `audio_features.*`. | Um `features.h` no include path sombreia o `<features.h>` da glibc e quebra qualquer `#include <stdio.h>` no alvo nativo. |
| D2 | Adendo do usuário à seção 9: Freesound **somente pela API oficial** (`ml/fetch_freesound.py`, chave em `FREESOUND_API_KEY`, nunca versionada), licenças CC0/CC-BY, até ~40 clipes, com `data/raw/smoke_real/SOURCES.csv`. Baixa-se o *preview* mp3 (o original exige OAuth2). | Autorizado explicitamente; substitui a regra "sem Freesound" só para o acesso oficial por API. Scraping continua proibido. |
| D3 | `data/raw/smoke_real_manual/` (clipes baixados pela aluna) = **conjunto de TESTE REAL**: nunca em treino nem validação; métricas reportadas em separado. `data/raw/demo/alarm_demo.wav` continua fora de tudo (só `--demo-clip`). | Adendo do usuário. Se, no total (API + manual), houver < 10 clipes reais, avisar a aluna antes de decidir. |
| D4 | Driver I2S legado `driver/i2s.h` (Arduino-ESP32 **2.0.17**, ESP-IDF 4.4, instalado por `espressif32@^6`; verificado em `~/.platformio/packages/framework-arduinoespressif32/package.json`). | Conforme seção 7; API estável e simples para RX mono de 32 bits. |
| D5 | T1 usa contadores **atômicos** (`overruns`, `mutex_timeouts`) e nenhum mutex; o overrun sobrescreve o bloco mais antigo com controle por número de sequência por slot (seqlock), e T2 descarta leituras rasgadas (`torn_reads`). | T1 é a tarefa mais crítica: nunca pode bloquear em mutex. |
| D6 | No modo `esp32-test`, T1 aplica contrapressão (espera com `vTaskDelay`) em vez de overrun quando o host envia mais rápido que o tempo real. | Testes determinísticos; overruns só são significativos na captura I2S real. |
| D7 | Modelo final = **regressão logística** (4 features), C=0,01 (escolhido por PR-AUC na validação; a curva é praticamente plana em C), limiar 0,9 e voto **N=6 de M=8** escolhidos por clipe na validação (maior recall com FPR ≤ 3%). N/M padrão 3/5 do CLAUDE.md foi substituído porque na validação não atingia o orçamento de falso alarme; `config.py` lê N/M de `models/model_params.json`. | Seção 5: o limiar e N/M só podem ser escolhidos na validação. |
| D8 | MLP (8 e 16 unidades) foi testado **só na validação**: recall sintético maior (98,7%) mas FPR de negativos difíceis pior (10–12,5% vs 7,5%) e nenhum ganho nos positivos reais. Mantida a regressão logística (metas globais já atendidas na validação; mais simples e auditável no ESP32). | Seção 2: MLP só se as metas não fossem atingidas. |
| D9 | Curadoria dos positivos reais do Freesound (`ml/curate_real.py`) e divisão **por autor**. Motivo: 12 dos 32 clipes não eram alarmes de fumaça ou estavam abaixo do gate; séries do mesmo autor são quase duplicatas. | Evita ruído de rótulo e vazamento entre treino e teste. |
| D10 | O conjunto de teste é lido por `ml/evaluate.py --split test` uma única vez (trava em `models/.test_used`). | Seção 5. |
