#include "mqtt_activation_publisher.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <ctime>

#include "esp_log.h"
#include "esp_random.h"
#include "mqtt_client.h"

#if __has_include("../mqtt_config.h")
#include "../mqtt_config.h"
#else
#define BWM_MQTT_BROKER_URI ""
#define BWM_MQTT_TOPIC_BASE "bwm"
#endif

namespace {
constexpr char kTag[] = "bwm.mqtt";

void eventHandler(void *handler_args, esp_event_base_t, int32_t event_id, void *)
{
    auto *connected = static_cast<std::atomic_bool *>(handler_args);
    if (event_id == MQTT_EVENT_CONNECTED) {
        connected->store(true);
        ESP_LOGI(kTag, "MQTT connected topic=%s/installation/activation qos=1 retained=false",
                 BWM_MQTT_TOPIC_BASE);
    }
    if (event_id == MQTT_EVENT_DISCONNECTED) {
        connected->store(false);
        ESP_LOGW(kTag, "MQTT disconnected; retrying");
    }
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
    esp_mqtt_client_register_event(mqtt, MQTT_EVENT_ANY, eventHandler, &connected_);
    if (esp_mqtt_client_start(mqtt) != ESP_OK) {
        ESP_LOGW(kTag, "MQTT start failed; detection continues locally");
        esp_mqtt_client_destroy(mqtt);
        return;
    }
    client_ = mqtt;
    ESP_LOGI(kTag, "MQTT starting topic=%s/installation/activation qos=1 retained=false",
             BWM_MQTT_TOPIC_BASE);
}

void MqttActivationPublisher::publishStateIfChanged(bool active)
{
    if (has_state_ && active == previous_state_) return;
    has_state_ = true;
    previous_state_ = active;

    // A falling edge only rearms the next camera activation. The Pi owns the
    // admitted session lifetime.
    if (!active) return;
    publishActivation("camera_confirmation", nullptr, 0);
}

bool MqttActivationPublisher::publishManualActivation(char *event_id, size_t event_id_size)
{
    return publishActivation("manual_test", event_id, event_id_size);
}

bool MqttActivationPublisher::publishActivation(const char *trigger_source,
                                                char *returned_event_id,
                                                size_t returned_event_id_size)
{
    char id[37];
    std::snprintf(id, sizeof(id), "%08lx-%04lx-%04lx-%04lx-%08lx%04lx",
                  static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random() & 0xffff),
                  static_cast<unsigned long>(esp_random() & 0xffff), static_cast<unsigned long>(esp_random() & 0xffff),
                  static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random() & 0xffff));
    if (returned_event_id != nullptr && returned_event_id_size > 0) {
        const size_t copy_length = std::min(returned_event_id_size - 1, std::strlen(id));
        std::memcpy(returned_event_id, id, copy_length);
        returned_event_id[copy_length] = '\0';
    }
    char timestamp[32];
    isoTimestamp(timestamp, sizeof(timestamp));
    char topic[96];
    std::snprintf(topic, sizeof(topic), "%s/installation/activation", BWM_MQTT_TOPIC_BASE);

    if (client_ == nullptr) {
        ESP_LOGW(kTag,
                 "activation not sent source=%s id=%s type=installation.activation origin=person_detector timestamp=%s topic=%s reason=mqtt_disabled_or_unavailable",
                 trigger_source, id, timestamp, topic);
        return false;
    }

    char payload[256];
    std::snprintf(payload, sizeof(payload),
                  "{\"version\":1,\"id\":\"%s\",\"type\":\"installation.activation\","
                  "\"origin\":\"person_detector\",\"timestamp\":\"%s\",\"payload\":{\"state\":\"active\"}}",
                  id, timestamp);
    // QoS 1, non-retained: the Translation runtime deduplicates IDs and state.
    const int message_id = esp_mqtt_client_publish(
        static_cast<esp_mqtt_client_handle_t>(client_), topic, payload, 0, 1, 0);
    if (message_id < 0) {
        ESP_LOGW(kTag,
                 "activation publish failed source=%s id=%s type=installation.activation origin=person_detector timestamp=%s topic=%s",
                 trigger_source, id, timestamp, topic);
        return false;
    }
    ESP_LOGI(kTag,
             "activation queued source=%s id=%s type=installation.activation origin=person_detector timestamp=%s topic=%s mqtt_message_id=%d connected=%s",
             trigger_source, id, timestamp, topic, message_id, connected_.load() ? "true" : "false");
    return true;
}
