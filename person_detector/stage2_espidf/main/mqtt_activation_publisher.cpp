#include "mqtt_activation_publisher.h"

#include <cstdio>

#include "esp_log.h"
#include "mqtt_client.h"

#if !__has_include("../mqtt_config.h")
#error "Missing stage2_espidf/mqtt_config.h: copy mqtt_config.h.example beside CMakeLists.txt and set BWM_MQTT_BROKER_URI"
#else
#include "../mqtt_config.h"
#endif

namespace {
constexpr char kTag[] = "bwm.mqtt";
}  // namespace

void MqttActivationPublisher::eventHandler(void *handler_args, esp_event_base_t,
                                           int32_t event_id, void *)
{
    auto *publisher = static_cast<MqttActivationPublisher *>(handler_args);
    if (event_id == MQTT_EVENT_CONNECTED) {
        publisher->connected_.store(true);
        publisher->publish_operational_.store(true);
        ESP_LOGI(kTag, "MQTT connected broker=%s topic=%s/installation/activation qos=1 retained=false",
                 BWM_MQTT_BROKER_URI, BWM_MQTT_TOPIC_BASE);
    }
    if (event_id == MQTT_EVENT_DISCONNECTED) {
        publisher->connected_.store(false);
        publisher->publish_operational_.store(false);
        ESP_LOGW(kTag, "MQTT disconnected broker=%s; retrying", BWM_MQTT_BROKER_URI);
    }
}

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
    esp_mqtt_client_register_event(mqtt, MQTT_EVENT_ANY, eventHandler, this);
    if (esp_mqtt_client_start(mqtt) != ESP_OK) {
        ESP_LOGW(kTag, "MQTT start failed; detection continues locally");
        esp_mqtt_client_destroy(mqtt);
        return;
    }
    client_ = mqtt;
    ESP_LOGI(kTag, "MQTT starting broker=%s topic=%s/installation/activation qos=1 retained=false",
             BWM_MQTT_BROKER_URI, BWM_MQTT_TOPIC_BASE);
}

const char *MqttActivationPublisher::brokerUri() const
{
    return BWM_MQTT_BROKER_URI;
}

bool MqttActivationPublisher::publish(const ActivationEvent &event)
{
    char topic[96];
    std::snprintf(topic, sizeof(topic), "%s/installation/activation", BWM_MQTT_TOPIC_BASE);

    if (client_ == nullptr) {
        ESP_LOGW(kTag,
                 "activation not sent source=%s id=%s type=installation.activation origin=person_detector timestamp=%s topic=%s reason=mqtt_disabled_or_unavailable",
                 event.trigger_source, event.id, event.timestamp, topic);
        return false;
    }

    // Keep the released MQTT envelope byte-for-byte compatible. Trigger-source
    // diagnostics remain in local logs; BLE carries them in its JSON envelope.
    char payload[256];
    const int payload_length = std::snprintf(
        payload, sizeof(payload),
        "{\"version\":1,\"id\":\"%s\",\"type\":\"installation.activation\","
        "\"origin\":\"person_detector\",\"timestamp\":\"%s\",\"payload\":{\"state\":\"active\"}}",
        event.id, event.timestamp);
    if (payload_length < 0 || static_cast<size_t>(payload_length) >= sizeof(payload)) return false;
    // QoS 1, non-retained: the Translation runtime deduplicates IDs and state.
    const int message_id = esp_mqtt_client_publish(
        static_cast<esp_mqtt_client_handle_t>(client_), topic, payload, 0, 1, 0);
    if (message_id < 0) {
        publish_operational_.store(false);
        ESP_LOGW(kTag,
                 "activation publish failed source=%s id=%s type=installation.activation origin=person_detector timestamp=%s topic=%s",
                 event.trigger_source, event.id, event.timestamp, topic);
        return false;
    }
    publish_operational_.store(connected_.load());
    ESP_LOGI(kTag,
             "activation queued source=%s id=%s type=installation.activation origin=person_detector timestamp=%s topic=%s mqtt_message_id=%d connected=%s",
             event.trigger_source, event.id, event.timestamp, topic, message_id, connected_.load() ? "true" : "false");
    return true;
}
