#pragma once

#include <atomic>
#include <cstddef>

// An adapter only: detector/camera code decides whether a person is present.
class MqttActivationPublisher {
public:
    void begin();
    // Only the inactive-to-active edge is published. Clearing motion must not
    // cancel the Pi's admitted session.
    void publishStateIfChanged(bool active);
    // Bypasses detector state only; it shares envelope construction and MQTT
    // publishing with camera-confirmed activation.
    bool publishManualActivation(char *event_id, size_t event_id_size);
private:
    bool publishActivation(const char *trigger_source, char *event_id, size_t event_id_size);
    void *client_ = nullptr;
    std::atomic_bool connected_{false};
    bool has_state_ = false;
    bool previous_state_ = false;
};
