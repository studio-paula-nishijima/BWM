#include <unity.h>
#include <string>
#ifdef ARDUINO
#include <Arduino.h>
#endif
#include "runtime_core.h"
#include "semantic_framing.h"

namespace {
bool levels[6];
void writer(uint8_t channel, bool high) { levels[channel] = high; }
}

void setUp() { for (bool& level : levels) level = false; }
void tearDown() {}

void test_safety_simultaneous_and_forced_off() {
  bwm::ActuatorSafety<6> safety({500, 40, 10000, 160, 9000}, writer);
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::AdmissionResult::kAccepted),
                        static_cast<int>(safety.admit(0, 150, 100)));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::AdmissionResult::kAccepted),
                        static_cast<int>(safety.admit(5, 150, 100)));
  TEST_ASSERT_TRUE(levels[0]);
  TEST_ASSERT_TRUE(levels[5]);
  safety.service(250);
  TEST_ASSERT_FALSE(levels[0]);
  TEST_ASSERT_FALSE(levels[5]);
  TEST_ASSERT_TRUE(safety.allLow());
}

void test_safety_validation_minimum_off_and_hard_limit() {
  bwm::ActuatorSafety<6> safety({500, 40, 10000, 160, 9000}, writer);
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::AdmissionResult::kInvalidChannel),
                        static_cast<int>(safety.admit(6, 150, 0)));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::AdmissionResult::kInvalidDuration),
                        static_cast<int>(safety.admit(0, 501, 0)));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::AdmissionResult::kAccepted),
                        static_cast<int>(safety.admit(0, 500, 10)));
  safety.service(510);
  TEST_ASSERT_FALSE(levels[0]);
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::AdmissionResult::kMinimumOff),
                        static_cast<int>(safety.admit(0, 150, 530)));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::AdmissionResult::kAccepted),
                        static_cast<int>(safety.admit(0, 150, 550)));
}

void test_fault_is_all_low_and_latched() {
  bwm::ActuatorSafety<6> safety({500, 40, 10000, 160, 9000}, writer);
  safety.admit(2, 150, 0);
  safety.latchFault(10);
  TEST_ASSERT_TRUE(safety.allLow());
  TEST_ASSERT_TRUE(safety.faulted());
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::AdmissionResult::kFaultLatched),
                        static_cast<int>(safety.admit(2, 150, 1000)));
}

void test_random_segment_is_indexed_immutable_and_rebased_by_origin() {
  const bwm::ScoreEvent score[] = {{100, 150, 0}, {200, 150, 1}, {700, 150, 2}, {900, 150, 3}};
  const auto selected = bwm::selectSegment(score, 4, 500, 0);
  TEST_ASSERT_EQUAL_UINT32(100, selected.source_start_ms);
  TEST_ASSERT_EQUAL_UINT(0, selected.begin);
  TEST_ASSERT_EQUAL_UINT(2, selected.end);
  TEST_ASSERT_EQUAL_UINT32(100, score[0].time_ms);
}

void test_session_idempotency_timeout_and_generation() {
  bwm::SessionState state;
  bwm::SessionSelection selected{1, 3, 200, 800};
  TEST_ASSERT_TRUE(state.activate(100, selected, 4000, 600000));
  const uint32_t generation = state.generation();
  TEST_ASSERT_FALSE(state.activate(101, selected, 4000, 600000));
  TEST_ASSERT_EQUAL_UINT32(generation, state.generation());
  TEST_ASSERT_FALSE(state.admissionOpen(4099));
  TEST_ASSERT_TRUE(state.admissionOpen(4100));
  TEST_ASSERT_TRUE(state.timedOut(600100));
  TEST_ASSERT_TRUE(state.deactivate());
  TEST_ASSERT_FALSE(state.deactivate());
  TEST_ASSERT_FALSE(state.active());
  TEST_ASSERT_TRUE(state.generation() > generation);
}

void test_recent_ids_shared_ttl_and_capacity_shape() {
  bwm::RecentIds ids;
  const auto hash = bwm::RecentIds::hash("same-semantic-id");
  TEST_ASSERT_FALSE(ids.seen(hash, 10));
  TEST_ASSERT_TRUE(ids.seen(hash, 11));
  TEST_ASSERT_FALSE(ids.seen(hash, 3600011));
  TEST_ASSERT_EQUAL_UINT(1024, bwm::RecentIds::kCapacity);
}

void test_uart_partial_multiple_and_oversize_recovery() {
  bwm::UartLineFramer<8> framer;
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::FrameResult::kIncomplete), static_cast<int>(framer.feed('{')));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::FrameResult::kComplete), static_cast<int>(framer.feed('\n')));
  TEST_ASSERT_EQUAL_STRING("{", framer.data());
  for (char value : std::string("123456789")) framer.feed(value);
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::FrameResult::kOversized), static_cast<int>(framer.feed('\n')));
  framer.feed('x');
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::FrameResult::kComplete), static_cast<int>(framer.feed('\n')));
  TEST_ASSERT_EQUAL_STRING("x", framer.data());
}

void test_ble_fragment_reassembly_and_gap_recovery() {
  bwm::BleFragmentFramer<32> framer;
  const uint8_t first[] = {0x01, 0x00, 0x00, 'a', 'b'};
  const uint8_t last[] = {0x02, 0x01, 0x00, 'c'};
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::FrameResult::kIncomplete), static_cast<int>(framer.feed(first, sizeof(first))));
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::FrameResult::kComplete), static_cast<int>(framer.feed(last, sizeof(last))));
  TEST_ASSERT_EQUAL_STRING("abc", framer.data());
  const uint8_t gap[] = {0x02, 0x02, 0x00, 'x'};
  TEST_ASSERT_EQUAL_INT(static_cast<int>(bwm::FrameResult::kMalformed), static_cast<int>(framer.feed(gap, sizeof(gap))));
}

void runTests() {
  UNITY_BEGIN();
  RUN_TEST(test_safety_simultaneous_and_forced_off);
  RUN_TEST(test_safety_validation_minimum_off_and_hard_limit);
  RUN_TEST(test_fault_is_all_low_and_latched);
  RUN_TEST(test_random_segment_is_indexed_immutable_and_rebased_by_origin);
  RUN_TEST(test_session_idempotency_timeout_and_generation);
  RUN_TEST(test_recent_ids_shared_ttl_and_capacity_shape);
  RUN_TEST(test_uart_partial_multiple_and_oversize_recovery);
  RUN_TEST(test_ble_fragment_reassembly_and_gap_recovery);
  UNITY_END();
}

#ifdef ARDUINO
void setup() { delay(2000); runTests(); }
void loop() {}
#else
int main(int, char**) { runTests(); return 0; }
#endif
