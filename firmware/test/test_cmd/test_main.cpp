// Testes Unity do interpretador de comandos de serial (GATE/THR/VOTE/MON/STATS).
#include <cstring>
#include <unity.h>
#include "runtime_params.h"

static RuntimeParams p;
static char reply[96];
void setUp() { params_defaults(&p); }
void tearDown() {}

static CmdKind run(const char* line) { return cmd_execute(line, &p, reply, sizeof reply); }

void test_defaults_from_headers() {
  TEST_ASSERT_EQUAL_FLOAT(DSP_RMS_GATE_DB, p.gate_db);
  TEST_ASSERT_EQUAL_INT(DSP_VOTE_N, p.vote_n);
  TEST_ASSERT_EQUAL_INT(DSP_VOTE_M, p.vote_m);
  TEST_ASSERT_FALSE(p.mon);
}

void test_gate() {
  TEST_ASSERT_EQUAL(CMD_SET, run("GATE -45"));
  TEST_ASSERT_EQUAL_FLOAT(-45.0f, p.gate_db);
  TEST_ASSERT_EQUAL_STRING("OK GATE -45.0", reply);
  TEST_ASSERT_EQUAL(CMD_SET, run("  gate   -62.5  "));   // maiúsc./minúsc. e espaços
  TEST_ASSERT_EQUAL_FLOAT(-62.5f, p.gate_db);
}

void test_gate_invalid_keeps_value() {
  p.gate_db = -50;
  TEST_ASSERT_EQUAL(CMD_ERR, run("GATE 5"));
  TEST_ASSERT_EQUAL(CMD_ERR, run("GATE -200"));
  TEST_ASSERT_EQUAL(CMD_ERR, run("GATE abc"));
  TEST_ASSERT_EQUAL(CMD_ERR, run("GATE"));
  TEST_ASSERT_EQUAL(CMD_ERR, run("GATE -45 extra"));
  TEST_ASSERT_EQUAL_FLOAT(-50.0f, p.gate_db);
  TEST_ASSERT_TRUE(strncmp(reply, "ERR", 3) == 0);
}

void test_thr() {
  TEST_ASSERT_EQUAL(CMD_SET, run("THR 0.85"));
  TEST_ASSERT_EQUAL_FLOAT(0.85f, p.thr);
  TEST_ASSERT_EQUAL(CMD_SET, run("THR 1"));
  TEST_ASSERT_EQUAL(CMD_ERR, run("THR 0"));
  TEST_ASSERT_EQUAL(CMD_ERR, run("THR 1.5"));
  TEST_ASSERT_EQUAL(CMD_ERR, run("THR -0.2"));
  TEST_ASSERT_EQUAL_FLOAT(1.0f, p.thr);
}

void test_vote() {
  TEST_ASSERT_EQUAL(CMD_SET, run("VOTE 3 5"));
  TEST_ASSERT_EQUAL_INT(3, p.vote_n);
  TEST_ASSERT_EQUAL_INT(5, p.vote_m);
  TEST_ASSERT_EQUAL_STRING("OK VOTE 3 5", reply);
  TEST_ASSERT_EQUAL(CMD_ERR, run("VOTE 6 5"));    // n > m
  TEST_ASSERT_EQUAL(CMD_ERR, run("VOTE 0 5"));
  TEST_ASSERT_EQUAL(CMD_ERR, run("VOTE 3 17"));   // m > DECISION_MAX_M
  TEST_ASSERT_EQUAL(CMD_ERR, run("VOTE 3"));
  TEST_ASSERT_EQUAL_INT(3, p.vote_n);             // inalterado após erros
  TEST_ASSERT_EQUAL_INT(5, p.vote_m);
}

void test_mon_and_stats() {
  TEST_ASSERT_EQUAL(CMD_SET, run("MON 1"));
  TEST_ASSERT_TRUE(p.mon);
  TEST_ASSERT_EQUAL(CMD_SET, run("mon 0"));
  TEST_ASSERT_FALSE(p.mon);
  TEST_ASSERT_EQUAL(CMD_ERR, run("MON 2"));
  TEST_ASSERT_EQUAL(CMD_STATS, run("STATS"));
}

void test_blank_and_unknown() {
  TEST_ASSERT_EQUAL(CMD_NONE, run(""));
  TEST_ASSERT_EQUAL(CMD_NONE, run("   "));
  TEST_ASSERT_EQUAL(CMD_ERR, run("FOO 1"));
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_defaults_from_headers);
  RUN_TEST(test_gate);
  RUN_TEST(test_gate_invalid_keeps_value);
  RUN_TEST(test_thr);
  RUN_TEST(test_vote);
  RUN_TEST(test_mon_and_stats);
  RUN_TEST(test_blank_and_unknown);
  return UNITY_END();
}
