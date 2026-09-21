# Guia do repositório (para explicar oralmente e responder por escrito)

Classificação usada em todas as tabelas:

- **EXIGIDO** — pedido pelo enunciado (segundo o resumo no `CLAUDE.md`): repositório com código, diagrama de tarefas, modelo `.onnx`, relatório técnico, código de teste que simula anomalias e mede desempenho.
- **ÚTIL** — não é pedido, mas o projeto funciona pior ou fica difícil de reproduzir/explicar sem ele.
- **EXTRA** — não é pedido e o projeto funciona sem ele (ver a seção B para removê-lo).

"Quem gera": **você** (escrito à mão/por mim no repositório), **script** (algum comando gera o arquivo) ou **treino** (`ml/train.py`).

---

## 1. Raiz do repositório

| Arquivo | O que é | Por que existe / quem gera | Classe | Se removido |
|---|---|---|---|---|
| `README.md` | Como preparar o ambiente, compilar, testar, gravar e reproduzir dados/treino | Porta de entrada do repositório; escrito por você | ÚTIL (o enunciado pede o repositório, não o README) | Ninguém sabe os comandos; nada quebra |
| `README` (sem extensão, 10 bytes) | Arquivo do commit inicial (`PONDERADA`) | Criado por você no primeiro commit | EXTRA | Nada muda |
| `CLAUDE.md` | Especificação que guiou a implementação | Escrito por você, para a IA | EXTRA (para a entrega) | Nada quebra; some o "porquê" das decisões |
| `requirements.txt` | Bibliotecas Python (numpy, scikit-learn, onnxruntime, PlatformIO…) | Você; usado por `pip install -r` | ÚTIL | Não dá para recriar o ambiente com um comando |
| `.gitignore` | Impede versionar áudio, `.venv`, `.pio`, `.env` | Você | ÚTIL (segurança: evita vazar a chave) | Áudio/segredos podem ser commitados por engano |
| `.env.example` | Modelo do `.env` (sem valor) para a chave do Freesound | Você | ÚTIL | Só some o lembrete de como configurar a chave |

## 2. `firmware/` — o programa do ESP32 (EXIGIDO)

| Arquivo / pasta | O que é | Por que existe / quem gera | Classe | Se removido |
|---|---|---|---|---|
| `platformio.ini` | Define os ambientes: `esp32dev`, `esp32-test`, `esp32-selftest`, `native`, `native-cli` | Você | EXIGIDO | Nada compila |
| `include/board_config.h` | Pinos, prioridades, núcleos, tamanhos de pilha, `I2S_SAMPLE_SHIFT`, `I2S_CHANNEL_SWAP` | Você (edição manual) | EXIGIDO | Firmware não compila |
| `include/dsp_config.h` | Constantes de DSP/decisão (16 kHz, 1024, 512, gate, N=6, M=8, cooldown) | **Script** `ml/gen_headers.py`, a partir de `ml/config.py` e do treino. Não edite à mão | EXIGIDO | Não compila; regenerar com `python -m ml.gen_headers` |
| `include/model_params.h` | Pesos da regressão logística (média, desvio, `w`, `b`) e `PROB_THRESHOLD` | **Script** `ml/gen_headers.py`, a partir de `models/model_params.json` (saída do **treino**) | EXIGIDO | Modelo some do firmware; regenerar com o mesmo comando |
| `lib/dsp/fft.*` | FFT de 1024 pontos e tabelas (Hann, seno/cosseno) | Você; sem dependência de Arduino, roda no PC | EXIGIDO | Sem espectro, sem features |
| `lib/dsp/audio_features.*` | Calcula RMS e as 4 features de uma janela | Você | EXIGIDO | Nada a classificar |
| `lib/dsp/model.*` | Faz a conta da regressão logística | Você | EXIGIDO | Sem detecção |
| `lib/dsp/decision.*` | Regra N de M, cooldown e supressão do buzzer | Você | EXIGIDO | Alarmes isolados/ruído disparariam sem controle |
| `lib/dsp/library.json` | Metadados da biblioteca para o PlatformIO | Você | EXTRA | Nada (PlatformIO detecta a pasta sozinho) |
| `src/main.cpp` | `setup()`: abre a serial, inicializa o DSP, cria as tarefas | Você | EXIGIDO | Firmware não inicia |
| `src/tasks.*` | As 4 tarefas, semáforo, fila, 2 mutexes, cronometragem | Você | EXIGIDO (é o núcleo RTOS) | Sem RTOS = sem projeto |
| `src/ring.*` | Buffer circular com número de sequência por slot | Você | EXIGIDO | Sem passagem segura T1→T2 |
| `src/audio_capture.*` | Leitura do I2S (ou da serial no `esp32-test`) e conversão 32→16 bits | Você | EXIGIDO | Sem áudio |
| `src/alert.*` | LED, buzzer opcional e supressão | Você | EXIGIDO (alerta por LED) | Sem alerta |
| `src/stats.*` | Contadores e cálculo de média/p50/p95 | Você | EXIGIDO (medir latência) | Sem estatísticas |
| `src/selftest.*` | Autoteste de bring-up (`esp32-selftest`) | Você | ÚTIL | Perde o teste de fiação; o ambiente `esp32-selftest` deixa de fazer sentido |
| `test/test_dsp/`, `test/test_decision/` | Testes Unity no PC (FFT, features, modelo, decisão) | Você; rodam com `pio test -e native` | EXIGIDO (código de teste) | Sem testes unitários |
| `tools/dsp_cli.cpp` | Executável de PC que roda o mesmo pipeline lendo o protocolo da serial | Você; usado por `parity_test.py` e `run_test.py` | ÚTIL (os testes do PC dependem dele) | `parity_test` e `run_test --target native` deixam de funcionar |

## 3. `ml/` — dados, treino e exportação

| Arquivo | O que é | Por que existe / quem gera | Classe | Se removido |
|---|---|---|---|---|
| `config.py` | Constantes (16 kHz, janela, banda, gate, N/M); lê N/M de `model_params.json` | Você; fonte da verdade | EXIGIDO | Nada roda em Python |
| `features.py` | Mesmas features do C++, em Python (referência) | Você | EXIGIDO | Sem treino nem paridade |
| `model.py`, `decision.py` | Espelhos em Python da inferência e da decisão | Você | ÚTIL (usados na avaliação e na paridade) | `evaluate.py`/paridade quebram |
| `gen_smoke_alarm.py` | Gerador de alarmes sintéticos (piezo 2,8–3,5 kHz, T3/T4, reverberação) | Você | EXIGIDO (dados de treino) | Perde metade dos positivos |
| `augment.py` | Augmentation (ganho, ruído, reverb, alto-falante…) só no treino | Você | ÚTIL (usado por `build_dataset.py`) | `build_dataset.py` quebra |
| `build_dataset.py` | Lê as fontes, divide por clipe, augmenta, rotula janelas, grava manifestos | Você; **script** | EXIGIDO | Não há como refazer o dataset |
| `train.py` | Treina, escolhe C/limiar/N de M **na validação** e grava o modelo | Você; **treino** | EXIGIDO | Sem modelo |
| `export_onnx.py` | Converte para `.onnx` e confere com o onnxruntime | Você; **script** | EXIGIDO (entrega o `.onnx`) | Sem `.onnx` |
| `gen_headers.py` | Gera `dsp_config.h` e `model_params.h` | Você; **script** | EXIGIDO | Modelo/constantes não chegam ao firmware |
| `evaluate.py` | Métricas por janela e por clipe, por tipo; trava do teste (`models/.test_used`) | Você; **script** | EXIGIDO (acurácia) | Sem números de validação/teste |
| `fetch_freesound.py` | Baixa clipes reais do Freesound pela API oficial (chave no `.env`) | Você; **script** | ÚTIL (positivos reais) | Não dá para rebaixar os reais |
| `curate_real.py` | Marca os clipes do Freesound que não são alarme (`EXCLUDED.csv`) | Você; **script** | ÚTIL | Clipes ruins entrariam no treino/teste |
| `__init__.py` | Marca a pasta como pacote Python | Você | ÚTIL | `python -m ml.xxx` falha |

## 4. `models/`

| Arquivo | O que é | Quem gera | Classe | Se removido |
|---|---|---|---|---|
| `detector.onnx` | **O modelo** (regressão logística com padronização, ~536 bytes) | **Script** `export_onnx.py` (a partir do **treino**) | **EXIGIDO** | Perde o entregável do enunciado (o firmware continua, pois usa o `.h`) |
| `model_params.json` | Pesos, limiar 0,9, N=6, M=8, C, data | **Treino** (`train.py`) | ÚTIL (alimenta `gen_headers.py`, `config.py` e a avaliação) | `config.py` volta a N=3/M=5 e a avaliação falha |
| `detector.joblib` | O mesmo modelo no formato do scikit-learn | **Treino** | EXTRA (só `export_onnx.py` o lê) | `export_onnx.py` não roda; nada mais |
| `.test_used` | Trava: registra que o teste já foi usado uma vez | **Script** `evaluate.py --split test` | ÚTIL (garante que o teste só vale uma vez) | Daria para rodar o teste de novo sem aviso |

## 5. `tests/` — código de teste (EXIGIDO)

| Arquivo | O que é | Classe | Se removido |
|---|---|---|---|
| `run_test.py` | Harness: acurácia por tipo, latência, `--simulate-anomalies`, `--demo-clip`, alvos `native`/`serial` | EXIGIDO (é o "código de teste que simula anomalias e mede performance") | Perde a simulação e a medição |
| `parity_test.py` | Prova que Python e C++ dão as mesmas features/probabilidades (e ONNX) | ÚTIL (defende a correção do modelo no ESP32) | Sem prova de equivalência |
| `cli_io.py` | Roda o `dsp_cli` e interpreta as linhas `W`/`A`/`S` | ÚTIL (usado pelos dois acima) | Os dois quebram |
| `fake_esp32.py` | ESP32 **falso** (pty + `dsp_cli`) para testar o lado do PC do alvo serial | EXTRA | Só perde esse ensaio; nada mais |
| `__init__.py` | Pacote Python | ÚTIL | `python -m tests.parity_test` falha |

## 6. `docs/`

| Arquivo | O que é | Quem gera | Classe | Se removido |
|---|---|---|---|---|
| `diagrama_tarefas.svg` | Diagrama de tarefas, mutexes, semáforo, fila e condições de corrida | Você (SVG à mão) | **EXIGIDO** | Perde um entregável |
| `relatorio_tecnico.md` | Arquitetura, latência, resultados, discussão | Você | **EXIGIDO** | Perde um entregável |
| `STUDY.md` | Guia de estudo (passeio pelo código, 12 perguntas de prova) | Você | ÚTIL (é longo; o guia curto pedido agora é este arquivo) | Perde material de estudo |
| `GUIA_DO_REPO.md` | Este arquivo | Você | ÚTIL | — |
| `HARDWARE_CHECKLIST.md` | Fiação, autoteste, calibração, medição no ESP32 | Você | ÚTIL (você vai montar o hardware) | Sem roteiro de hardware |
| `feature_spec.md` | Contrato exato das features (Python = C++) | Você | ÚTIL | Perde a "fonte da verdade"; nada quebra |
| `decisions.md` | Registro das decisões (N=6/M=8, MLP descartado, etc.) | Você | ÚTIL | Perde a justificativa |
| `latency_methodology.md` | Como cada latência é medida | Você | ÚTIL (o enunciado pede medir e documentar a latência) | Perde a explicação |
| `serial_protocol.md` | Formato das linhas `W`/`A`/`S` e do `START` | Você | EXTRA | Perde a especificação do protocolo |
| `PEDIDOS_PARA_ALUNA.md` | Pendências para você (ouvir clipes, clipe da demo) | Você | EXTRA | Some o lembrete |
| `results/` | Resultados reais dos testes (ver abaixo) | **Script** (`evaluate.py`, `run_test.py`) | ÚTIL (evidência dos números do relatório) | O relatório perde a fonte dos números |

### `docs/results/` (todos gerados por script, carimbados com data e alvo)

| Arquivo | O que é | Quem gera | Classe |
|---|---|---|---|
| `val_report_*_host.json`, `test_report_*_host.json` | Métricas por clipe/janela e por tipo (validação e teste) | `ml/evaluate.py` | ÚTIL |
| `val_confusao_pr_*_host.png`, `test_confusao_pr_*_host.png` | Matriz de confusão e curva precisão-recall | `ml/evaluate.py` | ÚTIL |
| `teste_val_*_native.{json,csv,png}`, `teste_test_*_native.{json,csv,png}` | Mesmo pipeline em C++ no PC: métricas, um alerta por clipe (csv) e latências do PC (png). **Tempos do host, não do ESP32** | `tests/run_test.py --target native` | ÚTIL (mostra que C++ = Python) |
| `simulacao_*_native.{json,csv,png}` | 40 cenas de 10 s com alarme em instante conhecido e o atraso até o alerta | `tests/run_test.py --simulate-anomalies` | EXIGIDO (é a saída da simulação de anomalias) |

## 7. `data/` (áudio nunca é versionado)

| Item | O que é | Quem gera | Classe |
|---|---|---|---|
| `data/README.md` | Fontes, licenças e como reproduzir | Você | ÚTIL (o relatório precisa citar fontes/licenças) |
| `data/raw/` (ignorado) | Áudio baixado: ESC-50, fala, Hugging Face, Freesound (`SOURCES.csv`, `EXCLUDED.csv`) | **Scripts** de download | ÚTIL |
| `data/processed/` (ignorado) | Clipes reamostrados, manifestos `*_manifest.csv` e janelas `windows_*.npz` | `ml/build_dataset.py` | ÚTIL |

Se `data/` for apagado, tudo pode ser refeito seguindo `data/README.md` (o firmware e os testes unitários não dependem dele).

---

## A. O mínimo indispensável para entrega e demo

**Entrega (o que o enunciado pede):**
1. Código: `firmware/` (menos `selftest.*` se quiser), `ml/`, `tests/`, `platformio.ini`, `requirements.txt`, `.gitignore`.
2. Diagrama: `docs/diagrama_tarefas.svg`.
3. Modelo: `models/detector.onnx` (e `model_params.json` para regenerar os `.h`).
4. Relatório: `docs/relatorio_tecnico.md` (+ os números de `docs/results/`).
5. Código de teste: `tests/run_test.py`, `firmware/test/`, `tests/parity_test.py`.
6. `README.md` e `data/README.md`.

**Demo:** placa montada (`docs/HARDWARE_CHECKLIST.md`), `pio run -e esp32dev -t upload`, monitor serial a 921600, um celular tocando o alarme, e o diagrama aberto. Plano B: `python tests/run_test.py --target native --demo-clip <arquivo.wav>` (mostra a decisão janela a janela).

## B. Extras que podem ser removidos sem quebrar builds nem testes

Verifiquei numa **cópia temporária** que, removendo todos os itens abaixo de uma vez, continuam passando: `pio test -e native` (13 testes), `pio run` nos 4 ambientes do firmware (`native-cli`, `esp32dev`, `esp32-test`, `esp32-selftest`), `python -m tests.parity_test` e os imports de `ml.*`. **Nada foi removido do seu repositório.** Cada comando abaixo só marca a remoção; depois é preciso `git commit`.

| Extra | Comando exato | Efeito colateral |
|---|---|---|
| `README` (10 bytes, sem extensão) | `git rm README` | nenhum |
| `CLAUDE.md` | `git rm CLAUDE.md` | some a especificação usada pela IA |
| `firmware/lib/dsp/library.json` | `git rm firmware/lib/dsp/library.json` | nenhum |
| `tests/fake_esp32.py` | `git rm tests/fake_esp32.py` | some o ensaio do lado do PC do alvo serial |
| `models/detector.joblib` | `git rm models/detector.joblib` | `python -m ml.export_onnx` só volta a funcionar depois de rodar `python -m ml.train` |
| `docs/serial_protocol.md` | `git rm docs/serial_protocol.md` | links em `README.md`/`HARDWARE_CHECKLIST.md` ficam quebrados |
| `docs/PEDIDOS_PARA_ALUNA.md` | `git rm docs/PEDIDOS_PARA_ALUNA.md` | some o lembrete de ouvir os clipes do Freesound |
| `docs/decisions.md` | `git rm docs/decisions.md` | o relatório cita "D7/D8"; a justificativa deixa de existir |
| `docs/feature_spec.md`, `docs/latency_methodology.md` | `git rm docs/feature_spec.md docs/latency_methodology.md` | links no relatório/README ficam quebrados |
| `docs/HARDWARE_CHECKLIST.md` | `git rm docs/HARDWARE_CHECKLIST.md` | perde o roteiro de montagem (**recomendo manter**) |
| `ml/fetch_freesound.py`, `ml/curate_real.py`, `.env.example` | `git rm ml/fetch_freesound.py ml/curate_real.py .env.example` | não dá mais para rebaixar/curar os clipes reais (os já baixados continuam) |
| Todos os resultados gerados | `git rm -r docs/results` | o relatório cita esses arquivos; os números seriam regeneráveis, mas o teste **só pode ser reavaliado com `--allow-test-rerun`** |

Para **mover** em vez de apagar (mantém o histórico e o arquivo): `mkdir -p extras && git mv docs/serial_protocol.md docs/PEDIDOS_PARA_ALUNA.md tests/fake_esp32.py extras/`. (Os `.md` movidos ficam com links relativos quebrados; nenhum código depende deles.)

**Não remova** (quebram build/teste): `ml/augment.py`, `ml/model.py`, `ml/decision.py`, `tests/cli_io.py`, `firmware/tools/dsp_cli.cpp`, `firmware/include/*.h`, `models/model_params.json`, `models/.test_used`, `tests/__init__.py`, `ml/__init__.py`.

## C. Dez perguntas que a professora poderia fazer (respostas curtas, do código real)

1. **Qual a diferença entre as 4 tarefas e por que essas prioridades?** T1 captura (prioridade 5, core 0), T2 features (3), T3 detecção (2), T4 monitor (1), definidas em `board_config.h`. A captura tem o prazo mais duro: o DMA do I2S guarda ~128 ms e depois perde amostras.
2. **Como T1 avisa T2?** `xSemaphoreGive(blocks_ready)` em `t1_audio_capture`; T2 dorme em `xSemaphoreTake(blocks_ready, portMAX_DELAY)`. Nenhuma tarefa faz espera ocupada.
3. **Como um overrun é detectado?** Quando o semáforo já está com 8 (máximo), o `Give` retorna falso e T1 incrementa `g_overruns`. O bloco mais antigo é sobrescrito e `ring_read` (número de sequência por slot) descarta leituras rasgadas.
4. **Onde poderia haver deadlock e por que não há?** Há dois mutexes (`log_mutex`, `stats_mutex`); nenhuma tarefa segura os dois juntos (`log_S_line` solta um antes de pegar o outro) e toda tomada usa timeout de 50 ms (`take()` em `tasks.cpp`).
5. **Por que mutex e não semáforo binário?** O mutex do FreeRTOS tem herança de prioridade, evitando que uma tarefa de baixa prioridade segurando o lock atrase uma de prioridade maior por causa de uma de prioridade média.
6. **Por que o ESP32 roda C++ se o entregável é `.onnx`?** O `.onnx` é o modelo validado (`export_onnx.py` confere com o onnxruntime); os pesos vão para `model_params.h` e `model_predict()` refaz `z = Σ w·(x−μ)/σ + b`. `parity_test.py` mostra erro ~1e-6 entre ONNX e C++.
7. **O que é o gate de −50 dBFS e a regra 6 de 8?** Janela abaixo de −50 dBFS é silêncio: nem roda o modelo (`t3_anomaly_detect`). O alerta exige 6 janelas positivas entre as últimas 8 (`decision_update`), com cooldown de 3 s; evita disparar em um estalo isolado.
8. **Como você evitou vazamento entre treino e teste?** A divisão é por clipe (nunca por janela), os positivos reais foram divididos por autor, a fala por locutor, o limiar e o N/M foram escolhidos só na validação e o teste foi lido uma vez (`models/.test_used`).
9. **Quais foram os resultados reais e o que não funcionou bem?** No teste, por clipe: recall 93,6% (73/78) e FPR 2,6% (12/466). Mas os negativos difíceis (sirene, buzina, despertador) dispararam em 7,5% (6/80) e só havia 3 alarmes reais no teste.
10. **Qual a latência do sistema?** Inerente: 64 ms de janela (passo de 32 ms) e ≥ 160 ms do voto 6 de 8. As latências do ESP32 (`t_sched`, `t_feat`, `t_queue`, `t_infer`, `t_total`) **ainda não foram medidas** (PENDENTE); as do PC (`t_feat` ≈ 17 µs de mediana) não valem para o ESP32.
