// Testes Unity: decisão N de M, cooldown e supressão do buzzer.
#include <unity.h>
#include "decision.h"

static DecisionState st;
void setUp() { decision_reset(&st); }
void tearDown() {}

static bool feed(bool pos, uint32_t ms, bool sup = false) {
  int64_t f = 0;
  return decision_update(&st, pos, ms, (int64_t)ms * 1000, sup, &f);
}

void test_needs_n_of_m() {
  TEST_ASSERT_FALSE(feed(1, 0));
  TEST_ASSERT_FALSE(feed(0, 32));
  TEST_ASSERT_FALSE(feed(1, 64));
  TEST_ASSERT_TRUE(feed(1, 96));  // 3 positivas nas últimas 4 (M=5)
}

void test_isolated_positives_do_not_alert() {
  for (int i = 0; i < 40; i++) TEST_ASSERT_FALSE(feed(i % 4 == 0, i * 32));  // 1 em 4: máx 2 em 5
}

void test_cooldown() {
  feed(1, 0); feed(1, 32);
  TEST_ASSERT_TRUE(feed(1, 64));
  for (int t = 96; t < 64 + DSP_COOLDOWN_MS; t += 32) TEST_ASSERT_FALSE(feed(1, t));
  TEST_ASSERT_TRUE(feed(1, 64 + DSP_COOLDOWN_MS));
}

void test_suppressed_ignored() {
  feed(1, 0); feed(1, 32);
  TEST_ASSERT_FALSE(feed(1, 64, true));  // ignorada: não entra no histórico
  TEST_ASSERT_TRUE(feed(1, 96));
}

void test_first_pos_time() {
  int64_t f = -1;
  decision_update(&st, 0, 0, 0, false, &f);
  decision_update(&st, 1, 32, 32000, false, &f);
  decision_update(&st, 1, 64, 64000, false, &f);
  TEST_ASSERT_TRUE(decision_update(&st, 1, 96, 96000, false, &f));
  TEST_ASSERT_EQUAL_INT64(32000, f);
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_needs_n_of_m);
  RUN_TEST(test_isolated_positives_do_not_alert);
  RUN_TEST(test_cooldown);
  RUN_TEST(test_suppressed_ignored);
  RUN_TEST(test_first_pos_time);
  return UNITY_END();
}
