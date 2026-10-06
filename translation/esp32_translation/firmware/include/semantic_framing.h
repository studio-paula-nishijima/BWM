#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace bwm {

enum class FrameResult : uint8_t { kIncomplete, kComplete, kMalformed, kOversized };

template <size_t MaxBytes>
class UartLineFramer {
 public:
  FrameResult feed(uint8_t byte) {
    if (byte == '\n') {
      if (discarding_) { reset(); return FrameResult::kOversized; }
      if (!size_) return FrameResult::kIncomplete;
      data_[size_] = 0;
      complete_size_ = size_;
      size_ = 0;
      return FrameResult::kComplete;
    }
    if (discarding_) return FrameResult::kIncomplete;
    if (size_ >= MaxBytes) {
      discarding_ = true;
      size_ = 0;
      return FrameResult::kIncomplete;
    }
    data_[size_++] = static_cast<char>(byte);
    return FrameResult::kIncomplete;
  }
  const char* data() const { return data_.data(); }
  size_t size() const { return complete_size_; }
  void reset() { size_ = complete_size_ = 0; discarding_ = false; }

 private:
  std::array<char, MaxBytes + 1> data_{};
  size_t size_ = 0;
  size_t complete_size_ = 0;
  bool discarding_ = false;
};

template <size_t MaxBytes>
class BleFragmentFramer {
 public:
  FrameResult feed(const uint8_t* frame, size_t length) {
    if (!frame || length < 4) { reset(); return FrameResult::kMalformed; }
    const uint8_t flags = frame[0];
    const uint16_t sequence = frame[1] | static_cast<uint16_t>(frame[2]) << 8;
    if (flags & ~0x03 || ((flags & 0x01) && sequence != 0)) {
      reset(); return FrameResult::kMalformed;
    }
    if (flags & 0x01) reset();
    else if (!started_) { reset(); return FrameResult::kMalformed; }
    if (sequence != next_sequence_) { reset(); return FrameResult::kMalformed; }
    const size_t payload = length - 3;
    if (size_ + payload > MaxBytes) { reset(); return FrameResult::kOversized; }
    started_ = true;
    memcpy(data_.data() + size_, frame + 3, payload);
    size_ += payload;
    ++next_sequence_;
    if (flags & 0x02) {
      data_[size_] = 0;
      complete_size_ = size_;
      started_ = false;
      size_ = 0;
      next_sequence_ = 0;
      return FrameResult::kComplete;
    }
    return FrameResult::kIncomplete;
  }
  const char* data() const { return data_.data(); }
  size_t size() const { return complete_size_; }
  void reset() { started_ = false; size_ = complete_size_ = 0; next_sequence_ = 0; }

 private:
  std::array<char, MaxBytes + 1> data_{};
  size_t size_ = 0;
  size_t complete_size_ = 0;
  uint16_t next_sequence_ = 0;
  bool started_ = false;
};

}  // namespace bwm
