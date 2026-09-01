#pragma once

#include <cstdint>

enum class AutomaticTransport : uint8_t { Mqtt = 0, Ble = 1 };

// Deliberately independent of Wi-Fi and BLE implementations so the hysteresis
// can be exercised deterministically without hardware.
class ActivationTransportPolicy {
public:
    static constexpr uint32_t kMqttUnavailableFallbackMs = 3000;
    static constexpr uint32_t kMqttHealthyReclaimMs = 10000;

    constexpr void reset(uint64_t now_ms)
    {
        current_ = AutomaticTransport::Mqtt;
        unhealthy_since_ms_ = now_ms;
        healthy_since_ms_ = kTimerNotRunning;
    }

    constexpr void update(uint64_t now_ms, bool mqtt_path_healthy)
    {
        if (current_ == AutomaticTransport::Mqtt) {
            healthy_since_ms_ = kTimerNotRunning;
            if (mqtt_path_healthy) {
                unhealthy_since_ms_ = kTimerNotRunning;
                return;
            }
            if (unhealthy_since_ms_ == kTimerNotRunning) unhealthy_since_ms_ = now_ms;
            if (now_ms - unhealthy_since_ms_ >= kMqttUnavailableFallbackMs) {
                current_ = AutomaticTransport::Ble;
                unhealthy_since_ms_ = kTimerNotRunning;
            }
            return;
        }

        unhealthy_since_ms_ = kTimerNotRunning;
        if (!mqtt_path_healthy) {
            healthy_since_ms_ = kTimerNotRunning;
            return;
        }
        if (healthy_since_ms_ == kTimerNotRunning) healthy_since_ms_ = now_ms;
        if (now_ms - healthy_since_ms_ >= kMqttHealthyReclaimMs) {
            current_ = AutomaticTransport::Mqtt;
            healthy_since_ms_ = kTimerNotRunning;
        }
    }

    constexpr AutomaticTransport current() const { return current_; }
    const char *currentName() const;
    constexpr uint32_t fallbackRemainingMs(uint64_t now_ms) const
    {
        return current_ == AutomaticTransport::Mqtt ?
            remaining(now_ms, unhealthy_since_ms_, kMqttUnavailableFallbackMs) : 0;
    }
    constexpr uint32_t reclaimRemainingMs(uint64_t now_ms) const
    {
        return current_ == AutomaticTransport::Ble ?
            remaining(now_ms, healthy_since_ms_, kMqttHealthyReclaimMs) : 0;
    }

private:
    static constexpr uint64_t kTimerNotRunning = UINT64_MAX;
    static constexpr uint32_t remaining(uint64_t now_ms, uint64_t started_ms, uint32_t threshold_ms)
    {
        if (started_ms == kTimerNotRunning) return 0;
        const uint64_t elapsed = now_ms - started_ms;
        return elapsed >= threshold_ms ? 0 : static_cast<uint32_t>(threshold_ms - elapsed);
    }

    AutomaticTransport current_ = AutomaticTransport::Mqtt;
    uint64_t unhealthy_since_ms_ = kTimerNotRunning;
    uint64_t healthy_since_ms_ = kTimerNotRunning;
};
