#include <unity.h>

#include "playback_safety.h"

namespace {

bool outputs[6]{};

void writeOutput(uint8_t channel, bool high) {
  if (channel < 6) {
    outputs[channel] = high;
  }
}

void resetOutputs() {
  for (bool& output : outputs) {
    output = false;
  }
}

void test_valid_event_admission() {
  resetOutputs();
  bwm_tuesday::SafetyController<6> safety(500, 100, writeOutput);
  TEST_ASSERT_EQUAL_UINT8(
      static_cast<uint8_t>(bwm_tuesday::AdmissionResult::kAccepted),
      static_cast<uint8_t>(safety.admit(2, 150, 1000)));
  TEST_ASSERT_TRUE(outputs[2]);
}

void test_invalid_channel_rejection() {
  bwm_tuesday::SafetyController<6> safety(500, 100, writeOutput);
  TEST_ASSERT_EQUAL_UINT8(
      static_cast<uint8_t>(bwm_tuesday::AdmissionResult::kInvalidChannel),
      static_cast<uint8_t>(safety.admit(6, 150, 0)));
}

void test_overlong_pulse_rejection() {
  bwm_tuesday::SafetyController<6> safety(500, 100, writeOutput);
  TEST_ASSERT_EQUAL_UINT8(
      static_cast<uint8_t>(bwm_tuesday::AdmissionResult::kInvalidDuration),
      static_cast<uint8_t>(safety.admit(0, 501, 0)));
}

void test_independent_forced_off() {
  resetOutputs();
  bwm_tuesday::SafetyController<6> safety(500, 100, writeOutput);
  TEST_ASSERT_EQUAL_UINT8(
      static_cast<uint8_t>(bwm_tuesday::AdmissionResult::kAccepted),
      static_cast<uint8_t>(safety.admit(0, 500, 10)));
  safety.service(510);
  TEST_ASSERT_FALSE(outputs[0]);
  TEST_ASSERT_TRUE(safety.allLow());
}

void test_simultaneous_events_on_separate_channels() {
  resetOutputs();
  bwm_tuesday::SafetyController<6> safety(500, 100, writeOutput);
  TEST_ASSERT_EQUAL_UINT8(0, static_cast<uint8_t>(safety.admit(1, 150, 1000)));
  TEST_ASSERT_EQUAL_UINT8(0, static_cast<uint8_t>(safety.admit(4, 150, 1000)));
  TEST_ASSERT_TRUE(outputs[1]);
  TEST_ASSERT_TRUE(outputs[4]);
}

void test_all_low_fault_state_action() {
  resetOutputs();
  bwm_tuesday::SafetyController<6> safety(500, 100, writeOutput);
  safety.admit(1, 150, 1000);
  safety.admit(4, 150, 1000);
  safety.forceAllOff(1010);
  TEST_ASSERT_TRUE(safety.allLow());
  for (bool output : outputs) {
    TEST_ASSERT_FALSE(output);
  }
}

void test_clean_loop_restart_after_gap() {
  resetOutputs();
  bwm_tuesday::SafetyController<6> safety(500, 100, writeOutput);
  safety.admit(0, 150, 0);
  safety.service(150);
  safety.forceAllOff(150);
  TEST_ASSERT_TRUE(safety.allLow());
  TEST_ASSERT_EQUAL_UINT8(
      static_cast<uint8_t>(bwm_tuesday::AdmissionResult::kAccepted),
      static_cast<uint8_t>(safety.admit(0, 150, 1650)));
  TEST_ASSERT_TRUE(outputs[0]);
}

}  // namespace

int runTests() {
  UNITY_BEGIN();
  RUN_TEST(test_valid_event_admission);
  RUN_TEST(test_invalid_channel_rejection);
  RUN_TEST(test_overlong_pulse_rejection);
  RUN_TEST(test_independent_forced_off);
  RUN_TEST(test_simultaneous_events_on_separate_channels);
  RUN_TEST(test_all_low_fault_state_action);
  RUN_TEST(test_clean_loop_restart_after_gap);
  return UNITY_END();
}

#ifdef ARDUINO

void setup() { (void)runTests(); }

void loop() {}

#else

int main(int, char**) {
  return runTests();
}

#endif
