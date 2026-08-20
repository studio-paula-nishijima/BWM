#pragma once

// An adapter only: detector/camera code decides whether a person is present.
class MqttActivationPublisher {
public:
    void begin();
    void publishStateIfChanged(bool active);
private:
    void *client_ = nullptr;
    bool has_state_ = false;
    bool previous_state_ = false;
};
