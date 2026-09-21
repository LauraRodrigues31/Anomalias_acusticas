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
