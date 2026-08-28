#include "ble_activation_publisher.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "host/ble_att.h"
#include "host/ble_gatt.h"
#include "host/ble_gap.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "os/os_mbuf.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

namespace {
constexpr char kTag[] = "bwm.ble";
constexpr char kDeviceName[] = "BWM Vision";
constexpr uint8_t kFrameStart = 0x01;
constexpr uint8_t kFrameEnd = 0x02;
constexpr size_t kFrameHeaderSize = 3;

// UUID strings (canonical order): 7a9e4c10-5b8d-4bd6-9c17-2f3e8a4b1001 and ...1002.
ble_uuid128_t kServiceUuid = BLE_UUID128_INIT(0x01, 0x10, 0x4b, 0x8a, 0x3e, 0x2f, 0x17, 0x9c,
                                                0xd6, 0x4b, 0x8d, 0x5b, 0x10, 0x4c, 0x9e, 0x7a);
ble_uuid128_t kActivationUuid = BLE_UUID128_INIT(0x02, 0x10, 0x4b, 0x8a, 0x3e, 0x2f, 0x17, 0x9c,
                                                   0xd6, 0x4b, 0x8d, 0x5b, 0x10, 0x4c, 0x9e, 0x7a);
uint16_t gActivationHandle = 0;
uint16_t gConnectionHandle = BLE_HS_CONN_HANDLE_NONE;
BleActivationPublisher *gPublisher = nullptr;
void startAdvertising();

int gapEvent(struct ble_gap_event *event, void *)
{
    if (gPublisher == nullptr) return 0;
    switch (event->type) {
        case BLE_GAP_EVENT_CONNECT:
            if (event->connect.status == 0) {
                gConnectionHandle = event->connect.conn_handle;
                gPublisher->onConnectionChanged(true, false);
                ESP_LOGI(kTag, "Pi connected");
            } else {
                ESP_LOGW(kTag, "connection failed status=%d", event->connect.status);
            }
            break;
        case BLE_GAP_EVENT_DISCONNECT:
            gConnectionHandle = BLE_HS_CONN_HANDLE_NONE;
            gPublisher->onConnectionChanged(false, true);
            ESP_LOGI(kTag, "Pi disconnected reason=%d; restarting advertising", event->disconnect.reason);
            // onSync is also safe to call after ordinary disconnects.
            startAdvertising();
            break;
        default:
            break;
    }
    return 0;
}

void startAdvertising()
{
    if (gPublisher == nullptr) return;
    ble_hs_adv_fields fields = {};
    fields.name = reinterpret_cast<const uint8_t *>(kDeviceName);
    fields.name_len = std::strlen(kDeviceName);
    fields.name_is_complete = 1;
    fields.uuids128 = &kServiceUuid;
    fields.num_uuids128 = 1;
    fields.uuids128_is_complete = 1;
    if (ble_gap_adv_set_fields(&fields) != 0) return;
    ble_gap_adv_params params = {};
    params.conn_mode = BLE_GAP_CONN_MODE_UND;
    params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    uint8_t address_type;
    if (ble_hs_id_infer_auto(0, &address_type) != 0) return;
    const int result = ble_gap_adv_start(address_type, nullptr, BLE_HS_FOREVER, &params, gapEvent, nullptr);
    gPublisher->onConnectionChanged(gPublisher->connected(), result == 0);
    ESP_LOGI(kTag, "BLE advertising %s", result == 0 ? "started" : "failed");
}

void onSync()
{
    uint8_t address_type;
    if (ble_hs_id_infer_auto(0, &address_type) == 0) {
        ble_gap_adv_stop();
        // Use inferred type rather than assuming a public address.
        ble_hs_adv_fields fields = {};
        fields.name = reinterpret_cast<const uint8_t *>(kDeviceName);
        fields.name_len = std::strlen(kDeviceName);
        fields.name_is_complete = 1;
        fields.uuids128 = &kServiceUuid;
        fields.num_uuids128 = 1;
        fields.uuids128_is_complete = 1;
        ble_gap_adv_set_fields(&fields);
        ble_gap_adv_params params = {};
        params.conn_mode = BLE_GAP_CONN_MODE_UND;
        params.disc_mode = BLE_GAP_DISC_MODE_GEN;
        const int result = ble_gap_adv_start(address_type, nullptr, BLE_HS_FOREVER, &params, gapEvent, nullptr);
        if (gPublisher != nullptr) gPublisher->onConnectionChanged(false, result == 0);
    }
}

void hostTask(void *)
{
    nimble_port_run();
    nimble_port_freertos_deinit();
}

ble_gatt_chr_def kCharacteristics[] = {
    {&kActivationUuid.u, nullptr, nullptr, nullptr, BLE_GATT_CHR_F_NOTIFY, 0, &gActivationHandle, nullptr},
    {},
};
ble_gatt_svc_def kServices[] = {
    {BLE_GATT_SVC_TYPE_PRIMARY, &kServiceUuid.u, nullptr, kCharacteristics},
    {},
};
}  // namespace

bool BleActivationPublisher::begin()
{
    if (gPublisher != nullptr) return gPublisher == this;
    gPublisher = this;
    if (nimble_port_init() != ESP_OK) return false;
    ble_svc_gap_init();
    ble_svc_gatt_init();
    ble_svc_gap_device_name_set(kDeviceName);
    ble_hs_cfg.sync_cb = onSync;
    if (ble_gatts_count_cfg(kServices) != 0 || ble_gatts_add_svcs(kServices) != 0) return false;
    nimble_port_freertos_init(hostTask);
    return true;
}

void BleActivationPublisher::onConnectionChanged(bool connected, bool advertising)
{
    connected_.store(connected);
    advertising_.store(advertising);
}

bool BleActivationPublisher::publish(const ActivationEvent &event)
{
    std::snprintf(last_event_id_, sizeof(last_event_id_), "%s", event.id);
    if (!connected_.load() || gConnectionHandle == BLE_HS_CONN_HANDLE_NONE) {
        std::snprintf(last_result_, sizeof(last_result_), "dropped_no_pi");
        ESP_LOGW(kTag, "activation dropped id=%s source=%s: no Pi connected", event.id, event.trigger_source);
        return false;
    }
    char json[320];
    if (!encodeActivationEventJson(event, json, sizeof(json))) {
        std::snprintf(last_result_, sizeof(last_result_), "encoding_failed");
        return false;
    }
    const size_t mtu = ble_att_mtu(gConnectionHandle);
    const size_t notification_payload = mtu > BLE_ATT_MTU_DFLT ? mtu - 3 : BLE_ATT_MTU_DFLT - 3;
    if (notification_payload <= kFrameHeaderSize) return false;
    const size_t chunk_size = notification_payload - kFrameHeaderSize;
    const size_t length = std::strlen(json);
    uint16_t sequence = 0;
    for (size_t offset = 0; offset < length;) {
        const size_t count = std::min(chunk_size, length - offset);
        uint8_t frame[3 + 244] = {};
        frame[0] = (offset == 0 ? kFrameStart : 0) | (offset + count == length ? kFrameEnd : 0);
        frame[1] = static_cast<uint8_t>(sequence & 0xff);
        frame[2] = static_cast<uint8_t>(sequence >> 8);
        std::memcpy(frame + kFrameHeaderSize, json + offset, count);
        os_mbuf *om = ble_hs_mbuf_from_flat(frame, kFrameHeaderSize + count);
        if (om == nullptr || ble_gatts_notify_custom(gConnectionHandle, gActivationHandle, om) != 0) {
            std::snprintf(last_result_, sizeof(last_result_), "notify_failed");
            return false;
        }
        offset += count;
        ++sequence;
    }
    std::snprintf(last_result_, sizeof(last_result_), "notified");
    ESP_LOGI(kTag, "activation notified id=%s source=%s chunks=%u", event.id, event.trigger_source,
             static_cast<unsigned>(sequence));
    return true;
}
