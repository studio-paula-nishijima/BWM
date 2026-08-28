#include "activation_transport.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "esp_log.h"
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
    mode_ = stored == static_cast<uint8_t>(ActivationTransportMode::Ble) ?
        ActivationTransportMode::Ble : ActivationTransportMode::Mqtt;
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
    if (mode_ == ActivationTransportMode::Mqtt) {
        mqtt_.begin();
        return true;
    }
    return ble_.begin();
}

const char *ActivationTransport::modeName() const
{
    return mode_ == ActivationTransportMode::Ble ? "ble" : "mqtt";
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
    const bool sent = mode_ == ActivationTransportMode::Ble ? ble_.publish(event) : mqtt_.publish(event);
    std::snprintf(last_event_id_, sizeof(last_event_id_), "%s", event.id);
    std::snprintf(last_result_, sizeof(last_result_), "%s", sent ? "sent" : "not_sent");
    if (event_id != nullptr && event_id_size > 0) {
        const size_t length = std::min(event_id_size - 1, std::strlen(event.id));
        std::memcpy(event_id, event.id, length);
        event_id[length] = '\0';
    }
    return sent;
}

const char *ActivationTransport::lastEventId() const
{
    return mode_ == ActivationTransportMode::Ble ? ble_.lastEventId() : last_event_id_;
}

const char *ActivationTransport::lastResult() const
{
    return mode_ == ActivationTransportMode::Ble ? ble_.lastResult() : last_result_;
}
