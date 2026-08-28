#include "activation_event.h"

#include <cstdio>
#include <cstring>
#include <ctime>

#include "esp_random.h"

bool makeActivationEvent(const char *trigger_source, ActivationEvent &event)
{
    if (trigger_source == nullptr || trigger_source[0] == '\0') return false;
    std::snprintf(event.id, sizeof(event.id), "%08lx-%04lx-%04lx-%04lx-%08lx%04lx",
                  static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random() & 0xffff),
                  static_cast<unsigned long>(esp_random() & 0xffff), static_cast<unsigned long>(esp_random() & 0xffff),
                  static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random() & 0xffff));
    const time_t now = time(nullptr);
    const tm *utc = gmtime(&now);
    if (utc == nullptr || strftime(event.timestamp, sizeof(event.timestamp), "%Y-%m-%dT%H:%M:%SZ", utc) == 0) {
        std::snprintf(event.timestamp, sizeof(event.timestamp), "1970-01-01T00:00:00Z");
    }
    std::snprintf(event.trigger_source, sizeof(event.trigger_source), "%s", trigger_source);
    return true;
}

bool encodeActivationEventJson(const ActivationEvent &event, char *json, size_t json_size)
{
    const int written = std::snprintf(
        json, json_size,
        "{\"version\":1,\"id\":\"%s\",\"type\":\"installation.activation\","
        "\"origin\":\"person_detector\",\"timestamp\":\"%s\","
        "\"payload\":{\"state\":\"active\"},\"diagnostics\":{\"trigger_source\":\"%s\"}}",
        event.id, event.timestamp, event.trigger_source);
    return written >= 0 && static_cast<size_t>(written) < json_size;
}
