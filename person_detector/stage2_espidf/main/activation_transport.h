#pragma once

#include <atomic>

#include "ble_activation_publisher.h"
#include "mqtt_activation_publisher.h"
#include "activation_transport_policy.h"

enum class ActivationTransportMode : uint8_t { Mqtt = 0, Ble = 1, Auto = 2 };

// Owns persistent transport selection and the single semantic construction
// path shared by camera-confirmed and manual activations.
class ActivationTransport {
public:
    ~ActivationTransport();
    bool begin();
    void updateNetworkHealth(bool wifi_has_ip, uint64_t now_ms);
    void publishStateIfChanged(bool active);
    bool publishManualActivation(char *event_id, size_t event_id_size);
    ActivationTransportMode mode() const { return mode_; }
    const char *modeName() const;
    bool selectMode(ActivationTransportMode mode);
    bool mqttConnected() const { return mqtt_.connected(); }
    bool mqttPathHealthy() const { return mqtt_path_healthy_.load(); }
    const char *mqttBrokerUri() const { return mqtt_.brokerUri(); }
    bool bleAdvertising() const { return ble_.advertising(); }
    bool bleConnected() const { return ble_.connected(); }
    const char *lastEventId() const;
    const char *lastResult() const;
    const char *currentTransportName() const;
    const char *lastActivationTransport() const { return last_activation_transport_; }
    const char *lastDropReason() const { return last_drop_reason_; }
    uint32_t fallbackRemainingMs(uint64_t now_ms) const;
    uint32_t reclaimRemainingMs(uint64_t now_ms) const;

private:
    bool dispatch(const char *trigger_source, char *event_id, size_t event_id_size);
    bool loadMode();
    bool saveMode();
    MqttActivationPublisher mqtt_;
    BleActivationPublisher ble_;
    ActivationTransportPolicy automatic_policy_;
    ActivationTransportMode mode_ = ActivationTransportMode::Ble;
    std::atomic_bool mqtt_path_healthy_{false};
    std::atomic<AutomaticTransport> automatic_current_{AutomaticTransport::Mqtt};
    std::atomic_uint32_t fallback_remaining_ms_{0};
    std::atomic_uint32_t reclaim_remaining_ms_{0};
    bool has_state_ = false;
    bool previous_state_ = false;
    char last_event_id_[37] = {};
    char last_result_[32] = "not_sent";
    char last_activation_transport_[16] = "none";
    char last_drop_reason_[40] = "none";
};
