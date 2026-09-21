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

// Testes independentes dos valores de N/M (vêm de dsp_config.h, gerado do treino).
void test_needs_n_of_m() {
  for (int i = 0; i < DSP_VOTE_N - 1; i++) TEST_ASSERT_FALSE(feed(1, i * 32));
  TEST_ASSERT_TRUE(feed(1, (DSP_VOTE_N - 1) * 32));  // N positivas seguidas => alerta
}

void test_isolated_positives_do_not_alert() {
  // 1 positiva a cada M+1 janelas: nunca chega a N (N >= 2)
  for (int i = 0; i < 60; i++) TEST_ASSERT_FALSE(feed(i % (DSP_VOTE_M + 1) == 0, i * 32));
}

void test_n_minus_1_does_not_alert() {
  for (int i = 0; i < DSP_VOTE_N - 1; i++) feed(1, i * 32);
  for (int i = 0; i < 20; i++) TEST_ASSERT_FALSE(feed(0, (DSP_VOTE_N + i) * 32));
}

void test_cooldown() {
  uint32_t t = 0;
  bool alerted = false;
  for (int i = 0; i < DSP_VOTE_N; i++, t += 32) alerted = feed(1, t);
  TEST_ASSERT_TRUE(alerted);
  const uint32_t t0 = t - 32;  // instante do alerta
  for (; t < t0 + DSP_COOLDOWN_MS; t += 32) TEST_ASSERT_FALSE(feed(1, t));
  TEST_ASSERT_TRUE(feed(1, t0 + DSP_COOLDOWN_MS));
}

void test_suppressed_ignored() {
  for (int i = 0; i < DSP_VOTE_N - 1; i++) feed(1, i * 32);
  TEST_ASSERT_FALSE(feed(1, 1000, true));                 // suprimida: não entra no histórico
  TEST_ASSERT_TRUE(feed(1, 1032));                        // a N-ésima positiva válida dispara
}

void test_first_pos_time() {
  int64_t f = -1;
  decision_update(&st, 0, 0, 0, false, &f);
  bool a = false;
  for (int i = 0; i < DSP_VOTE_N; i++) a = decision_update(&st, 1, 32 * (i + 1), 32000LL * (i + 1), false, &f);
  TEST_ASSERT_TRUE(a);
  TEST_ASSERT_EQUAL_INT64(32000, f);  // 1ª janela positiva do voto vencedor
}

int main() {
  UNITY_BEGIN();
  RUN_TEST(test_needs_n_of_m);
  RUN_TEST(test_isolated_positives_do_not_alert);
  RUN_TEST(test_n_minus_1_does_not_alert);
  RUN_TEST(test_cooldown);
  RUN_TEST(test_suppressed_ignored);
  RUN_TEST(test_first_pos_time);
  return UNITY_END();
}
