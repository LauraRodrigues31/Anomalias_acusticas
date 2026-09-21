#include "runtime_params.h"
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "model_params.h"

void params_defaults(RuntimeParams* p) {
  p->gate_db = DSP_RMS_GATE_DB;
  p->thr = PROB_THRESHOLD;
  p->vote_n = DSP_VOTE_N;
  p->vote_m = DSP_VOTE_M;
  p->mon = false;
}

static void set_reply(char* r, int cap, const char* fmt, double a = 0, double b = 0) {
  if (cap > 0) snprintf(r, (size_t)cap, fmt, a, b);
}

// Lê um float em s; true só se consumiu um número completo e finito.
static bool parse_float(const char* s, const char** end, float* out) {
  char* e = nullptr;
  const float v = strtof(s, &e);
  if (e == s || v != v || v > 1e9f || v < -1e9f) return false;
  *out = v;
  *end = e;
  return true;
}

static bool parse_int(const char* s, const char** end, int* out) {
  char* e = nullptr;
  const long v = strtol(s, &e, 10);
  if (e == s || v < -100000 || v > 100000) return false;
  *out = (int)v;
  *end = e;
  return true;
}

static const char* skip_ws(const char* s) {
  while (*s == ' ' || *s == '\t') s++;
  return s;
}

CmdKind cmd_execute(const char* line, RuntimeParams* p, char* reply, int cap) {
  if (cap > 0) reply[0] = 0;
  line = skip_ws(line);
  if (*line == 0 || *line == '\r') return CMD_NONE;
  char cmd[8];
  int n = 0;
  while (line[n] && !isspace((unsigned char)line[n]) && n < 7) {
    cmd[n] = (char)toupper((unsigned char)line[n]);
    n++;
  }
  cmd[n] = 0;
  const char* args = skip_ws(line + n);
  const char* end = args;

  if (strcmp(cmd, "STATS") == 0) return CMD_STATS;
  if (strcmp(cmd, "GATE") == 0) {
    float v;
    if (!parse_float(args, &end, &v) || *skip_ws(end) != 0) { set_reply(reply, cap, "ERR uso: GATE <dBFS>"); return CMD_ERR; }
    if (v < -120.0f || v > 0.0f) { set_reply(reply, cap, "ERR GATE fora de -120..0"); return CMD_ERR; }
    p->gate_db = v;
    set_reply(reply, cap, "OK GATE %.1f", v);
    return CMD_SET;
  }
  if (strcmp(cmd, "THR") == 0) {
    float v;
    if (!parse_float(args, &end, &v) || *skip_ws(end) != 0) { set_reply(reply, cap, "ERR uso: THR <0-1>"); return CMD_ERR; }
    if (!(v > 0.0f && v <= 1.0f)) { set_reply(reply, cap, "ERR THR fora de (0,1]"); return CMD_ERR; }
    p->thr = v;
    set_reply(reply, cap, "OK THR %.3f", v);
    return CMD_SET;
  }
  if (strcmp(cmd, "VOTE") == 0) {
    int vn, vm;
    if (!parse_int(args, &end, &vn) || !parse_int(skip_ws(end), &end, &vm) || *skip_ws(end) != 0) {
      set_reply(reply, cap, "ERR uso: VOTE <n> <m>");
      return CMD_ERR;
    }
    if (vn < 1 || vm < vn || vm > DECISION_MAX_M) { set_reply(reply, cap, "ERR VOTE exige 1<=n<=m<=16"); return CMD_ERR; }
    p->vote_n = vn;
    p->vote_m = vm;
    set_reply(reply, cap, "OK VOTE %.0f %.0f", vn, vm);
    return CMD_SET;
  }
  if (strcmp(cmd, "MON") == 0) {
    int v;
    if (!parse_int(args, &end, &v) || *skip_ws(end) != 0 || (v != 0 && v != 1)) { set_reply(reply, cap, "ERR uso: MON 1|0"); return CMD_ERR; }
    p->mon = (v == 1);
    set_reply(reply, cap, "OK MON %.0f", v);
    return CMD_SET;
  }
  set_reply(reply, cap, "ERR comando desconhecido (GATE THR VOTE MON STATS)");
  return CMD_ERR;
}
