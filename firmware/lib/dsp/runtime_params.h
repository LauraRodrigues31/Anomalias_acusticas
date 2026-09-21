// Parâmetros ajustáveis em tempo de execução (RAM) e interpretador dos comandos de serial do
// firmware de produção. Portátil e sem Arduino/FreeRTOS: testado no PC (firmware/test/test_cmd).
//
// Comandos (uma linha terminada em '\n'; maiúsculas/minúsculas indiferentes):
//   GATE <dBFS>      gate de RMS, -120..0            THR <p>     limiar de probabilidade, (0,1]
//   VOTE <n> <m>     regra n de m, 1<=n<=m<=16       MON 1|0     liga/desliga o monitor por janela
//   STATS            imprime as estatísticas agora e os parâmetros atuais (linha P,...)
// Os valores mudam só em RAM: um reset volta aos padrões dos headers gerados.
#pragma once
#include "dsp_config.h"
#include "decision.h"

struct RuntimeParams {
  float gate_db;
  float thr;
  int vote_n;
  int vote_m;
  bool mon;
};

void params_defaults(RuntimeParams* p);   // padrões: dsp_config.h / model_params.h

enum CmdKind { CMD_NONE, CMD_SET, CMD_STATS, CMD_ERR };

// Interpreta `line` (sem '\n'). Se válida, aplica em *p. `reply` recebe a resposta de uma linha
// ("OK GATE -45.0", "ERR ..."); vazia para linhas em branco. Retorna o tipo do comando.
CmdKind cmd_execute(const char* line, RuntimeParams* p, char* reply, int cap);
