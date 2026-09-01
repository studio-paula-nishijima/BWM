#pragma once

#include <atomic>

#include "activation_event.h"
#include <cstddef>
#include "esp_event.h"

// An adapter only: detector/camera code decides whether a person is present.
class MqttActivationPublisher {
public:
    void begin();
    bool publish(const ActivationEvent &event);
    bool connected() const { return connected_.load(); }
    bool pathOperational() const { return connected_.load() && publish_operational_.load(); }
    const char *brokerUri() const;
private:
    static void eventHandler(void *handler_args, esp_event_base_t event_base,
                             int32_t event_id, void *event_data);
    void *client_ = nullptr;
    std::atomic_bool connected_{false};
    std::atomic_bool publish_operational_{false};
};
