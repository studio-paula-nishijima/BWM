#include "activation_transport.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "esp_log.h"
#include "esp_timer.h"
#include "nvs.h"

namespace {
constexpr char kTag[] = "bwm.activation";
constexpr char kNamespace[] = "bwm_transport";
constexpr char kModeKey[] = "mode";
}

ActivationTransport::~ActivationTransport() = default;

bool ActivationTransport::loadMode()
{
    nvs_handle_t nvs;
    if (nvs_open(kNamespace, NVS_READWRITE, &nvs) != ESP_OK) return false;
    uint8_t stored = static_cast<uint8_t>(ActivationTransportMode::Mqtt);
    const esp_err_t result = nvs_get_u8(nvs, kModeKey, &stored);
    if (result == ESP_ERR_NVS_NOT_FOUND) {
        nvs_set_u8(nvs, kModeKey, stored);
        nvs_commit(nvs);
    }
    nvs_close(nvs);
    if (result != ESP_OK && result != ESP_ERR_NVS_NOT_FOUND) return false;
    if (stored == static_cast<uint8_t>(ActivationTransportMode::Ble)) {
        mode_ = ActivationTransportMode::Ble;
    } else if (stored == static_cast<uint8_t>(ActivationTransportMode::Auto)) {
        mode_ = ActivationTransportMode::Auto;
    } else {
        mode_ = ActivationTransportMode::Mqtt;
    }
    return true;
}

bool ActivationTransport::saveMode()
{
    nvs_handle_t nvs;
    if (nvs_open(kNamespace, NVS_READWRITE, &nvs) != ESP_OK) return false;
    const esp_err_t result = nvs_set_u8(nvs, kModeKey, static_cast<uint8_t>(mode_));
    const esp_err_t commit = result == ESP_OK ? nvs_commit(nvs) : result;
    nvs_close(nvs);
    return commit == ESP_OK;
}

bool ActivationTransport::begin()
{
    if (!loadMode()) {
        ESP_LOGW(kTag, "transport selection unavailable; defaulting to MQTT");
        mode_ = ActivationTransportMode::Mqtt;
    }
    ESP_LOGI(kTag, "selected activation transport=%s", modeName());
    const uint64_t now_ms = static_cast<uint64_t>(esp_timer_get_time() / 1000);
    automatic_policy_.reset(now_ms);
    automatic_current_.store(automatic_policy_.current());
    fallback_remaining_ms_.store(automatic_policy_.fallbackRemainingMs(now_ms));
    if (mode_ == ActivationTransportMode::Mqtt) {
        mqtt_.begin();
        return true;
    }
    if (mode_ == ActivationTransportMode::Ble) return ble_.begin();
    mqtt_.begin();
    const bool ble_started = ble_.begin();
    if (!ble_started) ESP_LOGW(kTag, "automatic fallback BLE initialization failed; MQTT remains available");
    return true;
}

const char *ActivationTransport::modeName() const
{
    if (mode_ == ActivationTransportMode::Ble) return "ble";
    if (mode_ == ActivationTransportMode::Auto) return "auto";
    return "mqtt";
}

void ActivationTransport::updateNetworkHealth(bool wifi_has_ip, uint64_t now_ms)
{
    const bool mqtt_path_healthy = wifi_has_ip && mqtt_.pathOperational();
    mqtt_path_healthy_.store(mqtt_path_healthy);
    if (mode_ != ActivationTransportMode::Auto) return;
    const AutomaticTransport before = automatic_policy_.current();
    automatic_policy_.update(now_ms, mqtt_path_healthy);
    automatic_current_.store(automatic_policy_.current());
    fallback_remaining_ms_.store(automatic_policy_.fallbackRemainingMs(now_ms));
    reclaim_remaining_ms_.store(automatic_policy_.reclaimRemainingMs(now_ms));
    if (before != automatic_policy_.current()) {
        ESP_LOGW(kTag, "automatic transport handover current=%s mqtt_path_healthy=%s",
                 automatic_policy_.currentName(), mqtt_path_healthy ? "true" : "false");
    }
}

bool ActivationTransport::selectMode(ActivationTransportMode mode)
{
    if (mode == mode_) return true;
    mode_ = mode;
    if (!saveMode()) return false;
    // A reboot gives ESP-IDF's network and NimBLE stacks a clean ownership
    // boundary; the UI tells the operator before it requests this change.
    return true;
}

void ActivationTransport::publishStateIfChanged(bool active)
{
    if (has_state_ && active == previous_state_) return;
    has_state_ = true;
    previous_state_ = active;
    if (active) dispatch("camera_confirmation", nullptr, 0);
}

bool ActivationTransport::publishManualActivation(char *event_id, size_t event_id_size)
{
    return dispatch("manual_test", event_id, event_id_size);
}

bool ActivationTransport::dispatch(const char *trigger_source, char *event_id, size_t event_id_size)
{
    ActivationEvent event;
    if (!makeActivationEvent(trigger_source, event)) return false;
    bool mqtt_attempted = false;
    bool mqtt_sent = false;
    bool ble_attempted = false;
    bool ble_sent = false;
    const bool use_ble = mode_ == ActivationTransportMode::Ble ||
        (mode_ == ActivationTransportMode::Auto && automatic_current_.load() == AutomaticTransport::Ble);
    if (use_ble) {
        ble_attempted = true;
        ble_sent = ble_.publish(event);
    } else {
        mqtt_attempted = true;
        mqtt_sent = mqtt_.publish(event);
        // A synchronous publish failure is stronger evidence than the periodic
        // health snapshot. In auto mode, give this same already-constructed
        // event to BLE once; never construct a second ID for the handover.
        if (!mqtt_sent && mode_ == ActivationTransportMode::Auto) {
            ble_attempted = true;
            ble_sent = ble_.publish(event);
            updateNetworkHealth(false, static_cast<uint64_t>(esp_timer_get_time() / 1000));
        }
    }
    const bool sent = mqtt_sent || ble_sent;
    std::snprintf(last_event_id_, sizeof(last_event_id_), "%s", event.id);
    const char *used = mqtt_sent && ble_sent ? "mqtt+ble" : mqtt_sent ? "mqtt" : ble_sent ? "ble" : "none";
    std::snprintf(last_activation_transport_, sizeof(last_activation_transport_), "%s", used);
    if (sent) {
        std::snprintf(last_result_, sizeof(last_result_), "sent_%s", used);
        std::snprintf(last_drop_reason_, sizeof(last_drop_reason_), "none");
    } else {
        const char *reason = mqtt_attempted && ble_attempted ? "mqtt_and_ble_unavailable" :
            mqtt_attempted ? "mqtt_unavailable" : "ble_unavailable_or_disconnected";
        std::snprintf(last_result_, sizeof(last_result_), "dropped");
        std::snprintf(last_drop_reason_, sizeof(last_drop_reason_), "%s", reason);
        ESP_LOGW(kTag, "activation dropped source=%s id=%s reason=%s", trigger_source, event.id, reason);
    }
    if (event_id != nullptr && event_id_size > 0) {
        const size_t length = std::min(event_id_size - 1, std::strlen(event.id));
        std::memcpy(event_id, event.id, length);
        event_id[length] = '\0';
    }
    return sent;
}

const char *ActivationTransport::lastEventId() const
{
    return last_event_id_;
}

const char *ActivationTransport::lastResult() const
{
    return last_result_;
}

const char *ActivationTransport::currentTransportName() const
{
    if (mode_ == ActivationTransportMode::Auto) {
        return automatic_current_.load() == AutomaticTransport::Ble ? "ble" : "mqtt";
    }
    return mode_ == ActivationTransportMode::Ble ? "ble" : "mqtt";
}

uint32_t ActivationTransport::fallbackRemainingMs(uint64_t now_ms) const
{
    (void)now_ms;
    return mode_ == ActivationTransportMode::Auto ? fallback_remaining_ms_.load() : 0;
}

uint32_t ActivationTransport::reclaimRemainingMs(uint64_t now_ms) const
{
    (void)now_ms;
    return mode_ == ActivationTransportMode::Auto ? reclaim_remaining_ms_.load() : 0;
}
