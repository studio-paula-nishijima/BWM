#pragma once

#include "ble_activation_publisher.h"
#include "mqtt_activation_publisher.h"

enum class ActivationTransportMode : uint8_t { Mqtt = 0, Ble = 1 };

// Owns persistent transport selection and the single semantic construction
// path shared by camera-confirmed and manual activations.
class ActivationTransport {
public:
    ~ActivationTransport();
    bool begin();
    void publishStateIfChanged(bool active);
    bool publishManualActivation(char *event_id, size_t event_id_size);
    ActivationTransportMode mode() const { return mode_; }
    const char *modeName() const;
    bool selectMode(ActivationTransportMode mode);
    bool mqttConnected() const { return mqtt_.connected(); }
    const char *mqttBrokerUri() const { return mqtt_.brokerUri(); }
    bool bleAdvertising() const { return ble_.advertising(); }
    bool bleConnected() const { return ble_.connected(); }
    const char *lastEventId() const;
    const char *lastResult() const;

private:
    bool dispatch(const char *trigger_source, char *event_id, size_t event_id_size);
    bool loadMode();
    bool saveMode();
    MqttActivationPublisher mqtt_;
    BleActivationPublisher ble_;
    ActivationTransportMode mode_ = ActivationTransportMode::Mqtt;
    bool has_state_ = false;
    bool previous_state_ = false;
    char last_event_id_[37] = {};
    char last_result_[32] = "not_sent";
};
