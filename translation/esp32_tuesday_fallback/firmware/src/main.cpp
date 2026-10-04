#include <Arduino.h>

#include "playback_safety.h"
#include "../../generated/score_data.h"

namespace {

constexpr uint8_t kChannelCount = 6;
constexpr uint8_t kOutputPins[kChannelCount] = {
    1,  // channel 0: XIAO D0 / GPIO1
    2,  // channel 1: XIAO D1 / GPIO2
    4,  // channel 2: XIAO D3 / GPIO4 (D2/GPIO3 is a reset strapping pin)
    5,  // channel 3: XIAO D4 / GPIO5
    6,  // channel 4: XIAO D5 / GPIO6
    7,  // channel 5: XIAO D8 / GPIO7
};
constexpr uint16_t kMaximumPulseMs = 500;
constexpr uint16_t kMinimumOffMs = 100;
constexpr uint32_t kLoopGapMs = 1500;
constexpr uint32_t kSerialBaud = 115200;

#ifndef BWM_TUESDAY_DEBUG_PULSES
#define BWM_TUESDAY_DEBUG_PULSES 0
#endif

enum class PlaybackState : uint8_t { kPlaying, kDraining, kLoopGap, kFault };

PlaybackState playback_state = PlaybackState::kPlaying;
size_t next_event_index = 0;
uint32_t score_epoch_ms = 0;
uint32_t loop_restart_ms = 0;

void writeOutput(uint8_t channel, bool high) {
  if (channel >= kChannelCount) {
    return;
  }
  digitalWrite(kOutputPins[channel], high ? HIGH : LOW);
}

bwm_tuesday::SafetyController<kChannelCount> safety(
    kMaximumPulseMs, kMinimumOffMs, writeOutput);

bool timeReached(uint32_t now_ms, uint32_t deadline_ms) {
  return static_cast<int32_t>(now_ms - deadline_ms) >= 0;
}

void enterFault(const char* reason, uint32_t now_ms) {
  safety.forceAllOff(now_ms);
  playback_state = PlaybackState::kFault;
  Serial.print("FAULT: ");
  Serial.println(reason);
}

void logRejectedEvent(size_t index, bwm_tuesday::AdmissionResult result) {
  Serial.print("event rejected at index ");
  Serial.print(index);
  Serial.print(": ");
  switch (result) {
    case bwm_tuesday::AdmissionResult::kInvalidChannel:
      Serial.println("invalid channel");
      break;
    case bwm_tuesday::AdmissionResult::kInvalidDuration:
      Serial.println("invalid duration");
      break;
    case bwm_tuesday::AdmissionResult::kChannelAlreadyHigh:
      Serial.println("channel already HIGH; existing OFF deadline retained");
      break;
    case bwm_tuesday::AdmissionResult::kMinimumOffTime:
      Serial.println("minimum OFF interval not met");
      break;
    case bwm_tuesday::AdmissionResult::kAccepted:
      break;
  }
}

void startScoreLoop(uint32_t now_ms) {
  safety.forceAllOff(now_ms);
  if (!safety.allLow()) {
    enterFault("outputs did not enter all-LOW state", now_ms);
    return;
  }
  next_event_index = 0;
  score_epoch_ms = now_ms;
  playback_state = PlaybackState::kPlaying;
  Serial.println("score playback starting");
}

void dispatchDueEvents(uint32_t now_ms) {
  const uint32_t elapsed_ms = now_ms - score_epoch_ms;
  while (next_event_index < bwm_tuesday::kScoreEventCount &&
         bwm_tuesday::kScoreEvents[next_event_index].time_ms <= elapsed_ms) {
    const size_t index = next_event_index++;
    const bwm_tuesday::ScoreEvent& event = bwm_tuesday::kScoreEvents[index];
    const bwm_tuesday::AdmissionResult result =
        safety.admit(event.channel, event.duration_ms, now_ms);
    if (result == bwm_tuesday::AdmissionResult::kInvalidChannel ||
        result == bwm_tuesday::AdmissionResult::kInvalidDuration) {
      logRejectedEvent(index, result);
      enterFault("compiled score failed runtime validation", now_ms);
      return;
    }
    if (result != bwm_tuesday::AdmissionResult::kAccepted) {
      logRejectedEvent(index, result);
    }
#if BWM_TUESDAY_DEBUG_PULSES
    else {
      Serial.print("pulse event ");
      Serial.println(index);
    }
#endif
  }

  if (next_event_index == bwm_tuesday::kScoreEventCount) {
    playback_state = PlaybackState::kDraining;
  }
}

}  // namespace

void setup() {
  // First application action: preload LOW, take ownership, then reaffirm LOW.
  // External gate pull-downs are still mandatory for reset/boot-time safety.
  for (uint8_t pin : kOutputPins) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }

  Serial.begin(kSerialBaud);
  Serial.println();
  Serial.println("BWM Tuesday Translation fallback");
  Serial.print("score events: ");
  Serial.println(bwm_tuesday::kScoreEventCount);
  Serial.print("score duration: ");
  Serial.print(bwm_tuesday::kScoreDurationMs);
  Serial.println(" ms");
  Serial.println("channels: 6");
  Serial.print("max pulse: ");
  Serial.print(kMaximumPulseMs);
  Serial.println(" ms");
  Serial.print("minimum OFF: ");
  Serial.print(kMinimumOffMs);
  Serial.println(" ms");
  startScoreLoop(millis());
}

void loop() {
  const uint32_t now_ms = millis();

  // Always service hardware safety first, independent of playback state/index.
  safety.service(now_ms);

  switch (playback_state) {
    case PlaybackState::kPlaying:
      dispatchDueEvents(now_ms);
      break;
    case PlaybackState::kDraining:
      if (safety.allLow()) {
        safety.forceAllOff(now_ms);
        loop_restart_ms = now_ms + kLoopGapMs;
        playback_state = PlaybackState::kLoopGap;
        Serial.println("score complete; outputs LOW");
      }
      break;
    case PlaybackState::kLoopGap:
      if (!safety.allLow()) {
        enterFault("output HIGH during loop gap", now_ms);
      } else if (timeReached(now_ms, loop_restart_ms)) {
        startScoreLoop(now_ms);
      }
      break;
    case PlaybackState::kFault:
      safety.forceAllOff(now_ms);
      delay(1);
      break;
  }
}
