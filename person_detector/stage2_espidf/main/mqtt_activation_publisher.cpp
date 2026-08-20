#include "mqtt_activation_publisher.h"

#include <cstdio>
#include <ctime>

#include "esp_log.h"
#include "esp_mqtt_client.h"
#include "esp_random.h"

#if __has_include("../mqtt_config.h")
#include "../mqtt_config.h"
#else
#define BWM_MQTT_BROKER_URI ""
#define BWM_MQTT_TOPIC_BASE "bwm"
#endif

namespace {
constexpr char kTag[] = "bwm.mqtt";

void eventHandler(void *, esp_event_base_t, int32_t event_id, void *)
{
    if (event_id == MQTT_EVENT_CONNECTED) ESP_LOGI(kTag, "MQTT connected");
    if (event_id == MQTT_EVENT_DISCONNECTED) ESP_LOGW(kTag, "MQTT disconnected; retrying");
}

void isoTimestamp(char *buffer, size_t size)
{
    const time_t now = time(nullptr);
    const tm *utc = gmtime(&now);
    if (utc == nullptr || strftime(buffer, size, "%Y-%m-%dT%H:%M:%SZ", utc) == 0) {
        std::snprintf(buffer, size, "1970-01-01T00:00:00Z");
    }
}
}  // namespace

void MqttActivationPublisher::begin()
{
    if (BWM_MQTT_BROKER_URI[0] == '\0') {
        ESP_LOGI(kTag, "MQTT disabled: no BWM_MQTT_BROKER_URI configured");
        return;
    }
    esp_mqtt_client_config_t config = {};
    config.broker.address.uri = BWM_MQTT_BROKER_URI;
    config.credentials.client_id = "person-detector";
    const esp_mqtt_client_handle_t mqtt = esp_mqtt_client_init(&config);
    if (mqtt == nullptr) {
        ESP_LOGW(kTag, "MQTT init failed; detection continues locally");
        return;
    }
    esp_mqtt_client_register_event(mqtt, MQTT_EVENT_ANY, eventHandler, nullptr);
    if (esp_mqtt_client_start(mqtt) != ESP_OK) {
        ESP_LOGW(kTag, "MQTT start failed; detection continues locally");
        esp_mqtt_client_destroy(mqtt);
        return;
    }
    client_ = mqtt;
}

void MqttActivationPublisher::publishStateIfChanged(bool active)
{
    if (has_state_ && active == previous_state_) return;
    has_state_ = true;
    previous_state_ = active;
    if (client_ == nullptr) return;

    char id[37];
    std::snprintf(id, sizeof(id), "%08lx-%04lx-%04lx-%04lx-%08lx%04lx",
                  static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random() & 0xffff),
                  static_cast<unsigned long>(esp_random() & 0xffff), static_cast<unsigned long>(esp_random() & 0xffff),
                  static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random() & 0xffff));
    char timestamp[32];
    isoTimestamp(timestamp, sizeof(timestamp));
    char payload[256];
    std::snprintf(payload, sizeof(payload),
                  "{\"version\":1,\"id\":\"%s\",\"type\":\"installation.activation\","
                  "\"origin\":\"person_detector\",\"timestamp\":\"%s\",\"payload\":{\"state\":\"%s\"}}",
                  id, timestamp, active ? "active" : "inactive");
    char topic[96];
    std::snprintf(topic, sizeof(topic), "%s/installation/activation", BWM_MQTT_TOPIC_BASE);
    // QoS 1, non-retained: the Translation runtime deduplicates IDs and state.
    esp_mqtt_client_publish(static_cast<esp_mqtt_client_handle_t>(client_), topic, payload, 0, 1, 0);
}
