#pragma once

#include <cstddef>

// Transport-independent installation activation. Both MQTT and BLE serialize
// this exact envelope; detector code only supplies the trigger source.
struct ActivationEvent {
    char id[37] = {};
    char timestamp[32] = {};
    char trigger_source[32] = {};
};

bool makeActivationEvent(const char *trigger_source, ActivationEvent &event);
bool encodeActivationEventJson(const ActivationEvent &event, char *json, size_t json_size);
