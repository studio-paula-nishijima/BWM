#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>

namespace bwm {

inline bool reached(uint32_t now, uint32_t deadline) {
  return static_cast<int32_t>(now - deadline) >= 0;
}

struct ScoreEvent {
  uint32_t time_ms;
  uint16_t duration_ms;
  uint8_t channel;
};

enum class AdmissionResult : uint8_t {
  kAccepted,
  kInvalidChannel,
  kInvalidDuration,
  kAlreadyHigh,
  kMinimumOff,
  kRunawayRate,
  kExtremeDuty,
  kFaultLatched,
};

struct SafetyLimits {
  uint16_t max_pulse_ms = 500;
  uint16_t min_off_ms = 40;
  uint32_t accounting_window_ms = 10000;
  uint16_t max_events_per_window = 160;
  uint32_t max_on_ms_per_window = 9000;
  constexpr SafetyLimits(uint16_t pulse = 500, uint16_t off = 40,
                         uint32_t window = 10000, uint16_t events = 160,
                         uint32_t duty = 9000)
      : max_pulse_ms(pulse), min_off_ms(off), accounting_window_ms(window),
        max_events_per_window(events), max_on_ms_per_window(duty) {}
};

template <size_t ChannelCount, size_t HistoryCount = 192>
class ActuatorSafety {
 public:
  using Writer = void (*)(uint8_t, bool);

  ActuatorSafety(SafetyLimits limits, Writer writer) : limits_(limits), writer_(writer) {}

  AdmissionResult admit(uint8_t channel, uint16_t duration_ms, uint32_t now) {
    if (fault_) return AdmissionResult::kFaultLatched;
    if (channel >= ChannelCount) return AdmissionResult::kInvalidChannel;
    if (duration_ms == 0 || duration_ms > limits_.max_pulse_ms) {
      return AdmissionResult::kInvalidDuration;
    }
    Channel& state = channels_[channel];
    if (state.high) return AdmissionResult::kAlreadyHigh;
    if (state.has_off && static_cast<uint32_t>(now - state.last_off_ms) < limits_.min_off_ms) {
      return AdmissionResult::kMinimumOff;
    }
    compact(state, now);
    if (state.history_size >= limits_.max_events_per_window || state.history_size >= HistoryCount) {
      return AdmissionResult::kRunawayRate;
    }
    uint32_t duty = duration_ms;
    for (size_t i = 0; i < state.history_size; ++i) duty += state.history[i].duration_ms;
    if (duty > limits_.max_on_ms_per_window) return AdmissionResult::kExtremeDuty;

    state.history[state.history_size++] = {now, duration_ms};
    state.high_since_ms = now;
    state.requested_off_ms = now + duration_ms;
    state.hard_off_ms = now + limits_.max_pulse_ms;
    state.high = true;
    last_accepted_ms_ = now;
    has_accepted_ = true;
    ++accepted_;
    writer_(channel, true);
    return AdmissionResult::kAccepted;
  }

  void service(uint32_t now) {
    for (uint8_t channel = 0; channel < ChannelCount; ++channel) {
      Channel& state = channels_[channel];
      if (state.high && (reached(now, state.requested_off_ms) || reached(now, state.hard_off_ms))) {
        turnOff(channel, now);
      }
    }
  }

  void forceAllOff(uint32_t now) {
    for (uint8_t channel = 0; channel < ChannelCount; ++channel) {
      writer_(channel, false);
      if (channels_[channel].high) {
        channels_[channel].has_off = true;
        channels_[channel].last_off_ms = now;
      }
      channels_[channel].high = false;
    }
  }

  void latchFault(uint32_t now) {
    fault_ = true;
    forceAllOff(now);
  }

  bool allLow() const {
    for (const Channel& state : channels_) if (state.high) return false;
    return true;
  }
  bool faulted() const { return fault_; }
  bool hasAccepted() const { return has_accepted_; }
  uint32_t lastAcceptedMs() const { return last_accepted_ms_; }
  uint32_t acceptedCount() const { return accepted_; }

 private:
  struct History { uint32_t at_ms; uint16_t duration_ms; };
  struct Channel {
    bool high = false;
    bool has_off = false;
    uint32_t high_since_ms = 0;
    uint32_t requested_off_ms = 0;
    uint32_t hard_off_ms = 0;
    uint32_t last_off_ms = 0;
    std::array<History, HistoryCount> history{};
    size_t history_size = 0;
  };

  void compact(Channel& state, uint32_t now) {
    size_t keep = 0;
    for (size_t i = 0; i < state.history_size; ++i) {
      if (static_cast<uint32_t>(now - state.history[i].at_ms) < limits_.accounting_window_ms) {
        state.history[keep++] = state.history[i];
      }
    }
    state.history_size = keep;
  }

  void turnOff(uint8_t channel, uint32_t now) {
    writer_(channel, false);
    Channel& state = channels_[channel];
    state.high = false;
    state.has_off = true;
    state.last_off_ms = now;
  }

  SafetyLimits limits_;
  Writer writer_;
  std::array<Channel, ChannelCount> channels_{};
  bool fault_ = false;
  bool has_accepted_ = false;
  uint32_t last_accepted_ms_ = 0;
  uint32_t accepted_ = 0;
};

struct SessionSelection {
  size_t begin = 0;
  size_t end = 0;
  uint32_t source_start_ms = 0;
  uint32_t source_end_ms = 0;
  constexpr SessionSelection(size_t first = 0, size_t last = 0,
                             uint32_t source_first = 0, uint32_t source_last = 0)
      : begin(first), end(last), source_start_ms(source_first), source_end_ms(source_last) {}
};

inline SessionSelection selectSegment(const ScoreEvent* events, size_t count,
                                      uint32_t segment_ms, uint32_t random_value) {
  SessionSelection result{};
  if (!events || count == 0) return result;
  const uint32_t first = events[0].time_ms;
  const uint32_t last = events[count - 1].time_ms;
  const uint32_t duration = last - first;
  uint32_t start = first;
  if (segment_ms < duration) {
    const uint32_t span = duration - segment_ms;
    start = first + (span == std::numeric_limits<uint32_t>::max()
                         ? random_value
                         : random_value % (span + 1));
  }
  const uint32_t finish = (segment_ms >= duration) ? last + 1 : start + segment_ms;
  const ScoreEvent* begin = std::lower_bound(events, events + count, start,
      [](const ScoreEvent& event, uint32_t value) { return event.time_ms < value; });
  const ScoreEvent* end = std::lower_bound(begin, events + count, finish,
      [](const ScoreEvent& event, uint32_t value) { return event.time_ms < value; });
  if (begin == end) { begin = events; end = events + count; }
  result.begin = static_cast<size_t>(begin - events);
  result.end = static_cast<size_t>(end - events);
  result.source_start_ms = begin->time_ms;
  result.source_end_ms = finish;
  return result;
}

class SessionState {
 public:
  bool activate(uint32_t now, const SessionSelection& selection,
                uint32_t admission_delay_ms, uint32_t timeout_ms) {
    if (active_) return false;
    active_ = true;
    ++generation_;
    started_ms_ = now;
    admission_ms_ = now + admission_delay_ms;
    timeout_ms_ = now + timeout_ms;
    selection_ = selection;
    next_ = selection.begin;
    return true;
  }
  bool deactivate() {
    if (!active_) return false;
    active_ = false;
    ++generation_;
    selection_ = {};
    next_ = 0;
    return true;
  }
  bool timedOut(uint32_t now) const { return active_ && reached(now, timeout_ms_); }
  bool admissionOpen(uint32_t now) const { return active_ && reached(now, admission_ms_); }
  uint32_t scoreElapsed(uint32_t now) const { return now - admission_ms_; }
  bool active() const { return active_; }
  uint32_t generation() const { return generation_; }
  size_t next() const { return next_; }
  void advance() { ++next_; }
  const SessionSelection& selection() const { return selection_; }

 private:
  bool active_ = false;
  uint32_t generation_ = 0;
  uint32_t started_ms_ = 0;
  uint32_t admission_ms_ = 0;
  uint32_t timeout_ms_ = 0;
  SessionSelection selection_{};
  size_t next_ = 0;
};

class RecentIds {
 public:
  static constexpr size_t kCapacity = 1024;
  static constexpr uint32_t kTtlMs = 3600000;

  bool seen(uint64_t id_hash, uint32_t now) {
    size_t oldest = 0;
    uint32_t oldest_age = 0;
    for (size_t i = 0; i < kCapacity; ++i) {
      if (entries_[i].used) {
        const uint32_t age = now - entries_[i].seen_ms;
        if (age >= kTtlMs) entries_[i].used = false;
        else if (entries_[i].hash == id_hash) return true;
        else if (age >= oldest_age) { oldest = i; oldest_age = age; }
      }
      if (!entries_[i].used) {
        entries_[i].hash = id_hash; entries_[i].seen_ms = now; entries_[i].used = true;
        return false;
      }
    }
    entries_[oldest].hash = id_hash; entries_[oldest].seen_ms = now; entries_[oldest].used = true;
    return false;
  }

  static uint64_t hash(const char* value) {
    uint64_t result = 1469598103934665603ULL;
    if (!value) return result;
    while (*value) { result ^= static_cast<uint8_t>(*value++); result *= 1099511628211ULL; }
    return result;
  }

 private:
  struct Entry { uint64_t hash = 0; uint32_t seen_ms = 0; bool used = false; };
  std::array<Entry, kCapacity> entries_{};
};

}  // namespace bwm
