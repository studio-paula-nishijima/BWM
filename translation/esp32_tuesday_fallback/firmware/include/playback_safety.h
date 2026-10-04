#pragma once

#include <cstddef>
#include <cstdint>

namespace bwm_tuesday {

enum class AdmissionResult : uint8_t {
  kAccepted,
  kInvalidChannel,
  kInvalidDuration,
  kChannelAlreadyHigh,
  kMinimumOffTime,
};

struct ChannelState {
  bool high = false;
  bool has_turned_off = false;
  uint32_t high_since_ms = 0;
  uint32_t off_deadline_ms = 0;
  uint32_t last_off_ms = 0;
};

using OutputWriter = void (*)(uint8_t channel, bool high);

inline bool deadlineReached(uint32_t now_ms, uint32_t deadline_ms) {
  return static_cast<int32_t>(now_ms - deadline_ms) >= 0;
}

template <size_t ChannelCount>
class SafetyController {
 public:
  SafetyController(uint16_t max_pulse_ms, uint16_t min_off_ms, OutputWriter writer)
      : max_pulse_ms_(max_pulse_ms), min_off_ms_(min_off_ms), writer_(writer) {}

  AdmissionResult admit(uint8_t channel, uint16_t duration_ms, uint32_t now_ms) {
    if (channel >= ChannelCount) {
      return AdmissionResult::kInvalidChannel;
    }
    if (duration_ms == 0 || duration_ms > max_pulse_ms_) {
      return AdmissionResult::kInvalidDuration;
    }

    ChannelState& state = channels_[channel];
    if (state.high) {
      return AdmissionResult::kChannelAlreadyHigh;
    }
    if (state.has_turned_off && static_cast<uint32_t>(now_ms - state.last_off_ms) < min_off_ms_) {
      return AdmissionResult::kMinimumOffTime;
    }

    // Establish both independent bounds before the physical HIGH transition.
    state.high_since_ms = now_ms;
    state.off_deadline_ms = now_ms + duration_ms;
    state.high = true;
    writer_(channel, true);
    return AdmissionResult::kAccepted;
  }

  void service(uint32_t now_ms) {
    for (uint8_t channel = 0; channel < ChannelCount; ++channel) {
      ChannelState& state = channels_[channel];
      const bool deadline_expired = state.high && deadlineReached(now_ms, state.off_deadline_ms);
      const bool hard_limit_expired =
          state.high && static_cast<uint32_t>(now_ms - state.high_since_ms) >= max_pulse_ms_;
      if (deadline_expired || hard_limit_expired) {
        turnOff(channel, now_ms);
      }
    }
  }

  void forceAllOff(uint32_t now_ms) {
    for (uint8_t channel = 0; channel < ChannelCount; ++channel) {
      writer_(channel, false);
      ChannelState& state = channels_[channel];
      if (state.high) {
        state.has_turned_off = true;
        state.last_off_ms = now_ms;
      }
      state.high = false;
    }
  }

  bool allLow() const {
    for (const ChannelState& state : channels_) {
      if (state.high) {
        return false;
      }
    }
    return true;
  }

 private:
  void turnOff(uint8_t channel, uint32_t now_ms) {
    writer_(channel, false);
    ChannelState& state = channels_[channel];
    state.high = false;
    state.has_turned_off = true;
    state.last_off_ms = now_ms;
  }

  ChannelState channels_[ChannelCount]{};
  uint16_t max_pulse_ms_;
  uint16_t min_off_ms_;
  OutputWriter writer_;
};

}  // namespace bwm_tuesday
