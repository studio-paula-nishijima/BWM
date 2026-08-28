#pragma once

#include <atomic>

#include "activation_event.h"
#include <cstddef>

// An adapter only: detector/camera code decides whether a person is present.
class MqttActivationPublisher {
public:
    void begin();
    bool publish(const ActivationEvent &event);
    bool connected() const { return connected_.load(); }
    const char *brokerUri() const;
private:
    void *client_ = nullptr;
    std::atomic_bool connected_{false};
};
