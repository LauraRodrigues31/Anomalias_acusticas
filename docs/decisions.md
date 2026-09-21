# Decisões de projeto

As decisões fechadas estão na seção 2 do `CLAUDE.md`. Este arquivo registra decisões tomadas durante a implementação e qualquer desvio (com justificativa).

| # | Decisão | Justificativa |
|---|---|---|
| D0 | Ambiente Python em `.venv/` (ignorado pelo git), PlatformIO instalado via pip nele. | `pio` não estava instalado no sistema. |
| D1 | `firmware/lib/dsp/features.*` chama-se `audio_features.*`. | Um `features.h` no include path sombreia o `<features.h>` da glibc e quebra qualquer `#include <stdio.h>` no alvo nativo. |
