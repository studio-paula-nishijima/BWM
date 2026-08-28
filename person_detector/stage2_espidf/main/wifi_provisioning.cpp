#include "wifi_provisioning.h"

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <new>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"

class WifiProvisioningManager::Impl {
public:
    EventGroupHandle_t events = nullptr;
    nvs_handle_t nvs = 0;
    bool nvs_available = false;
    bool wifi_started = false;
    std::atomic_bool connected{false};
    std::atomic_bool provisioning{false};
    std::atomic_bool recovering{false};
    std::atomic_bool provisioning_attempt{false};
    std::atomic_bool reconnect_scheduled{false};
    std::atomic_bool recovery_task_started{false};
    std::atomic_bool ap_stop_scheduled{false};
    std::atomic_bool restart_scheduled{false};
    std::atomic_uint retry_count{0};
    std::atomic_uint recovery_generation{0};
    std::atomic_llong next_recovery_retry_us{0};
    TaskHandle_t recovery_task = nullptr;
    char saved_ssid[33] = {};
    char saved_password[65] = {};
    char setup_ap_ssid[33] = {};
};

namespace {
constexpr char kTag[] = "bwm.wifi";
constexpr char kNamespace[] = "bwm_wifi";
constexpr char kSsidKey[] = "ssid";
constexpr char kPasswordKey[] = "password";
constexpr char kSetupPassword[] = "bwm-setup";
constexpr EventBits_t kConnectedBit = BIT0;
constexpr EventBits_t kFailedBit = BIT1;
constexpr unsigned kMaximumConnectionAttempts = 5;
constexpr TickType_t kReconnectDelay = pdMS_TO_TICKS(3000);
constexpr TickType_t kConnectionTimeout = pdMS_TO_TICKS(25000);
constexpr TickType_t kRecoveryRetryDelay = pdMS_TO_TICKS(5 * 60 * 1000);

void copyText(char *destination, size_t capacity, const char *source)
{
    if (capacity == 0) return;
    const char *value = source == nullptr ? "" : source;
    const size_t length = std::min(capacity - 1, std::strlen(value));
    std::memcpy(destination, value, length);
    destination[length] = '\0';
}

void setMessage(char *message, size_t size, const char *value)
{
    copyText(message, size, value);
}

bool validCredentials(const char *ssid, const char *password)
{
    if (ssid == nullptr || password == nullptr) return false;
    const size_t ssid_length = std::strlen(ssid);
    const size_t password_length = std::strlen(password);
    return ssid_length >= 1 && ssid_length <= 32 &&
           (password_length == 0 || (password_length >= 8 && password_length <= 63));
}

bool loadCredentials(WifiProvisioningManager::Impl &impl)
{
    if (!impl.nvs_available) return false;
    size_t ssid_size = sizeof(impl.saved_ssid);
    size_t password_size = sizeof(impl.saved_password);
    const esp_err_t ssid_result = nvs_get_str(impl.nvs, kSsidKey, impl.saved_ssid, &ssid_size);
    const esp_err_t password_result = nvs_get_str(impl.nvs, kPasswordKey, impl.saved_password, &password_size);
    if (ssid_result != ESP_OK || password_result != ESP_OK ||
        !validCredentials(impl.saved_ssid, impl.saved_password)) {
        impl.saved_ssid[0] = '\0';
        impl.saved_password[0] = '\0';
        return false;
    }
    return true;
}

bool saveCredentials(WifiProvisioningManager::Impl &impl, const char *ssid, const char *password)
{
    if (!impl.nvs_available) return false;
    if (nvs_set_str(impl.nvs, kSsidKey, ssid) != ESP_OK ||
        nvs_set_str(impl.nvs, kPasswordKey, password) != ESP_OK ||
        nvs_commit(impl.nvs) != ESP_OK) return false;
    copyText(impl.saved_ssid, sizeof(impl.saved_ssid), ssid);
    copyText(impl.saved_password, sizeof(impl.saved_password), password);
    return true;
}

wifi_config_t stationConfig(const char *ssid, const char *password)
{
    wifi_config_t config = {};
    const size_t ssid_length = std::min(std::strlen(ssid), sizeof(config.sta.ssid));
    const size_t password_length = std::min(std::strlen(password), sizeof(config.sta.password));
    std::memcpy(config.sta.ssid, ssid, ssid_length);
    std::memcpy(config.sta.password, password, password_length);
    config.sta.threshold.authmode = WIFI_AUTH_OPEN;
    config.sta.pmf_cfg.capable = true;
    config.sta.pmf_cfg.required = false;
    return config;
}

wifi_config_t setupApConfig(const char *ssid)
{
    wifi_config_t config = {};
    copyText(reinterpret_cast<char *>(config.ap.ssid), sizeof(config.ap.ssid), ssid);
    copyText(reinterpret_cast<char *>(config.ap.password), sizeof(config.ap.password), kSetupPassword);
    config.ap.ssid_len = std::strlen(ssid);
    config.ap.channel = 1;
    config.ap.max_connection = 4;
    config.ap.authmode = WIFI_AUTH_WPA2_PSK;
    config.ap.pmf_cfg.capable = true;
    config.ap.pmf_cfg.required = false;
    return config;
}

bool startProvisioningMode(WifiProvisioningManager::Impl &impl)
{
    impl.connected.store(false);
    impl.provisioning.store(true);
    impl.recovering.store(false);
    impl.recovery_generation.fetch_add(1);
    impl.next_recovery_retry_us.store(0);
    if (impl.recovery_task != nullptr) xTaskNotifyGive(impl.recovery_task);
    impl.provisioning_attempt.store(false);
    impl.retry_count.store(0);
    xEventGroupClearBits(impl.events, kConnectedBit);
    wifi_config_t ap_config = setupApConfig(impl.setup_ap_ssid);
    esp_err_t result = esp_wifi_set_mode(WIFI_MODE_APSTA);
    if (result == ESP_OK) result = esp_wifi_set_config(WIFI_IF_AP, &ap_config);
    if (result == ESP_OK && !impl.wifi_started) {
        result = esp_wifi_start();
        if (result == ESP_OK) impl.wifi_started = true;
    }
    if (result == ESP_OK) result = esp_wifi_set_ps(WIFI_PS_NONE);
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "could not start setup AP: %s", esp_err_to_name(result));
        return false;
    }
    ESP_LOGW(kTag,
             "setup mode active: join SSID=%s password=%s then open http://192.168.4.1/",
             impl.setup_ap_ssid, kSetupPassword);
    return true;
}

void recoveryRetryTask(void *argument)
{
    auto *impl = static_cast<WifiProvisioningManager::Impl *>(argument);
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        while (impl->recovering.load()) {
            const unsigned generation = impl->recovery_generation.load();
            impl->next_recovery_retry_us.store(
                esp_timer_get_time() + static_cast<int64_t>(5 * 60 * 1000000LL));
            ESP_LOGI(kTag, "saved network retry scheduled in 5 minutes");
            if (ulTaskNotifyTake(pdTRUE, kRecoveryRetryDelay) != 0) continue;

            if (!impl->recovering.load() || generation != impl->recovery_generation.load()) continue;
            impl->next_recovery_retry_us.store(0);
            ESP_LOGI(kTag, "recovery retry: attempting saved SSID=%s", impl->saved_ssid);
            const esp_err_t result = esp_wifi_connect();
            if (result != ESP_OK) {
                ESP_LOGW(kTag, "recovery connection request failed: %s", esp_err_to_name(result));
            }
        }
        impl->next_recovery_retry_us.store(0);
    }
}

bool ensureRecoveryTask(WifiProvisioningManager::Impl &impl)
{
    if (impl.recovery_task_started.exchange(true)) return true;
    if (xTaskCreate(recoveryRetryTask, "wifi_recovery", 3072, &impl, 4,
                    &impl.recovery_task) != pdPASS) {
        impl.recovery_task_started.store(false);
        ESP_LOGE(kTag, "could not start saved-network recovery task");
        return false;
    }
    return true;
}

bool startRecoveryMode(WifiProvisioningManager::Impl &impl)
{
    if (impl.recovering.load()) return true;
    impl.connected.store(false);
    impl.provisioning.store(false);
    impl.provisioning_attempt.store(false);
    impl.recovering.store(true);
    impl.retry_count.store(0);
    impl.recovery_generation.fetch_add(1);
    impl.next_recovery_retry_us.store(0);
    xEventGroupClearBits(impl.events, kConnectedBit);

    wifi_config_t station_config = stationConfig(impl.saved_ssid, impl.saved_password);
    wifi_config_t ap_config = setupApConfig(impl.setup_ap_ssid);
    esp_err_t result = esp_wifi_set_mode(WIFI_MODE_APSTA);
    if (result == ESP_OK) result = esp_wifi_set_config(WIFI_IF_STA, &station_config);
    if (result == ESP_OK) result = esp_wifi_set_config(WIFI_IF_AP, &ap_config);
    if (result == ESP_OK && !impl.wifi_started) {
        result = esp_wifi_start();
        if (result == ESP_OK) impl.wifi_started = true;
    }
    if (result == ESP_OK) result = esp_wifi_set_ps(WIFI_PS_NONE);
    if (result != ESP_OK) {
        impl.recovering.store(false);
        ESP_LOGE(kTag, "could not start recovery AP: %s", esp_err_to_name(result));
        return false;
    }

    if (!ensureRecoveryTask(impl)) return false;
    xTaskNotifyGive(impl.recovery_task);
    ESP_LOGW(kTag,
             "recovery mode active: saved SSID=%s unavailable; join SSID=%s password=%s and open http://192.168.4.1/",
             impl.saved_ssid, impl.setup_ap_ssid, kSetupPassword);
    return true;
}

void stopRecoveryApTask(void *argument)
{
    auto *impl = static_cast<WifiProvisioningManager::Impl *>(argument);
    const esp_err_t result = esp_wifi_set_mode(WIFI_MODE_STA);
    if (result == ESP_OK) {
        ESP_LOGI(kTag, "saved network recovered; temporary recovery AP stopped");
    } else {
        ESP_LOGW(kTag, "saved network recovered but recovery AP stop failed: %s",
                 esp_err_to_name(result));
    }
    impl->ap_stop_scheduled.store(false);
    vTaskDelete(nullptr);
}

void scheduleRecoveryApStop(WifiProvisioningManager::Impl &impl)
{
    if (impl.ap_stop_scheduled.exchange(true)) return;
    if (xTaskCreate(stopRecoveryApTask, "wifi_ap_stop", 2048, &impl, 4, nullptr) != pdPASS) {
        impl.ap_stop_scheduled.store(false);
        ESP_LOGW(kTag, "could not schedule recovery AP shutdown");
    }
}

void restartTask(void *)
{
    vTaskDelay(pdMS_TO_TICKS(1800));
    ESP_LOGI(kTag, "restarting to apply Wi-Fi configuration");
    esp_restart();
}

void scheduleRestart(WifiProvisioningManager::Impl &impl)
{
    if (impl.restart_scheduled.exchange(true)) return;
    if (xTaskCreate(restartTask, "wifi_restart", 2048, nullptr, 4, nullptr) != pdPASS) {
        impl.restart_scheduled.store(false);
        ESP_LOGE(kTag, "could not schedule restart");
    }
}

void reconnectTask(void *argument)
{
    auto *impl = static_cast<WifiProvisioningManager::Impl *>(argument);
    vTaskDelay(kReconnectDelay);
    impl->reconnect_scheduled.store(false);
    if (impl->connected.load() || impl->recovering.load() ||
        (impl->provisioning.load() && !impl->provisioning_attempt.load())) {
        vTaskDelete(nullptr);
        return;
    }

    if (impl->retry_count.load() >= kMaximumConnectionAttempts) {
        xEventGroupSetBits(impl->events, kFailedBit);
        if (!impl->provisioning_attempt.load()) startRecoveryMode(*impl);
        vTaskDelete(nullptr);
        return;
    }

    const unsigned attempt = impl->retry_count.fetch_add(1) + 1;
    ESP_LOGW(kTag, "station reconnect attempt %u/%u", attempt, kMaximumConnectionAttempts);
    const esp_err_t result = esp_wifi_connect();
    if (result != ESP_OK) {
        ESP_LOGW(kTag, "station reconnect request failed: %s", esp_err_to_name(result));
        xEventGroupSetBits(impl->events, kFailedBit);
    }
    vTaskDelete(nullptr);
}

void scheduleReconnect(WifiProvisioningManager::Impl &impl)
{
    if (impl.reconnect_scheduled.exchange(true)) return;
    if (xTaskCreate(reconnectTask, "wifi_reconnect", 3072, &impl, 4, nullptr) != pdPASS) {
        impl.reconnect_scheduled.store(false);
        xEventGroupSetBits(impl.events, kFailedBit);
        ESP_LOGE(kTag, "could not schedule station reconnect");
    }
}

void wifiEventHandler(void *argument, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    auto &impl = *static_cast<WifiProvisioningManager::Impl *>(argument);
    if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        const auto *event = static_cast<const ip_event_got_ip_t *>(event_data);
        impl.connected.store(true);
        impl.retry_count.store(0);
        xEventGroupClearBits(impl.events, kFailedBit);
        xEventGroupSetBits(impl.events, kConnectedBit);
        ESP_LOGI(kTag, "station connected ip=" IPSTR, IP2STR(&event->ip_info.ip));
        if (impl.recovering.exchange(false)) {
            impl.recovery_generation.fetch_add(1);
            impl.next_recovery_retry_us.store(0);
            if (impl.recovery_task != nullptr) xTaskNotifyGive(impl.recovery_task);
            scheduleRecoveryApStop(impl);
        }
        return;
    }
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        const auto *event = static_cast<const wifi_event_sta_disconnected_t *>(event_data);
        impl.connected.store(false);
        xEventGroupClearBits(impl.events, kConnectedBit);
        ESP_LOGW(kTag, "station disconnected reason=%u", static_cast<unsigned>(event->reason));
        if (impl.recovering.load()) {
            ESP_LOGI(kTag, "saved-network retry will remain on the 5-minute recovery cadence");
        } else if (!impl.provisioning.load() || impl.provisioning_attempt.load()) {
            scheduleReconnect(impl);
        }
    }
}
}  // namespace

WifiProvisioningManager::~WifiProvisioningManager()
{
    if (impl_ == nullptr) return;
    if (impl_->nvs_available) nvs_close(impl_->nvs);
    if (impl_->events != nullptr) vEventGroupDelete(impl_->events);
    delete impl_;
}

bool WifiProvisioningManager::begin()
{
    impl_ = new (std::nothrow) Impl();
    if (impl_ == nullptr) return false;
    impl_->events = xEventGroupCreate();
    if (impl_->events == nullptr) return false;

    const esp_err_t nvs_result = nvs_flash_init();
    const esp_err_t nvs_open_result = nvs_result == ESP_OK ?
        nvs_open(kNamespace, NVS_READWRITE, &impl_->nvs) : nvs_result;
    if (nvs_open_result == ESP_OK) {
        impl_->nvs_available = true;
    } else {
        ESP_LOGW(kTag, "credential persistence unavailable: %s", esp_err_to_name(nvs_open_result));
    }

    uint8_t mac[6] = {};
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    std::snprintf(impl_->setup_ap_ssid, sizeof(impl_->setup_ap_ssid),
                  "BWM-Vision-%02X%02X%02X", mac[3], mac[4], mac[5]);

    esp_err_t result = esp_netif_init();
    if (result != ESP_OK && result != ESP_ERR_INVALID_STATE) return false;
    result = esp_event_loop_create_default();
    if (result != ESP_OK && result != ESP_ERR_INVALID_STATE) return false;
    if (esp_netif_create_default_wifi_sta() == nullptr || esp_netif_create_default_wifi_ap() == nullptr) return false;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    if (esp_wifi_init(&init) != ESP_OK) return false;
    if (esp_wifi_set_storage(WIFI_STORAGE_RAM) != ESP_OK) return false;
    if (esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifiEventHandler, impl_, nullptr) != ESP_OK ||
        esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifiEventHandler, impl_, nullptr) != ESP_OK) {
        return false;
    }
    if (!loadCredentials(*impl_)) {
        ESP_LOGI(kTag, "no saved Wi-Fi credentials");
        return startProvisioningMode(*impl_);
    }

    ESP_LOGI(kTag, "loaded saved Wi-Fi SSID=%s", impl_->saved_ssid);
    wifi_config_t config = stationConfig(impl_->saved_ssid, impl_->saved_password);
    if (esp_wifi_set_mode(WIFI_MODE_STA) != ESP_OK ||
        esp_wifi_set_config(WIFI_IF_STA, &config) != ESP_OK ||
        esp_wifi_start() != ESP_OK) return false;
    impl_->wifi_started = true;
    if (esp_wifi_set_ps(WIFI_PS_NONE) != ESP_OK) return false;
    impl_->retry_count.store(1);
    if (esp_wifi_connect() != ESP_OK) return startRecoveryMode(*impl_);

    const EventBits_t bits = xEventGroupWaitBits(
        impl_->events, kConnectedBit | kFailedBit, pdFALSE, pdFALSE, kConnectionTimeout);
    if ((bits & kConnectedBit) != 0) return true;
    ESP_LOGW(kTag, "saved network unavailable after bounded retries; entering recovery mode");
    return startRecoveryMode(*impl_);
}

bool WifiProvisioningManager::connected() const
{
    return impl_ != nullptr && impl_->connected.load();
}

bool WifiProvisioningManager::provisioning() const
{
    return impl_ != nullptr && impl_->provisioning.load();
}

bool WifiProvisioningManager::recovering() const
{
    return impl_ != nullptr && impl_->recovering.load();
}

bool WifiProvisioningManager::hasSavedCredentials() const
{
    return impl_ != nullptr && impl_->saved_ssid[0] != '\0';
}

const char *WifiProvisioningManager::setupApSsid() const
{
    return impl_ == nullptr ? "BWM-Vision" : impl_->setup_ap_ssid;
}

const char *WifiProvisioningManager::operatingModeName() const
{
    if (impl_ == nullptr) return "unavailable";
    if (impl_->provisioning.load()) return "provisioning";
    if (impl_->recovering.load()) return "recovery";
    return impl_->connected.load() ? "normal" : "connecting";
}

uint32_t WifiProvisioningManager::recoveryRetrySeconds() const
{
    if (impl_ == nullptr || !impl_->recovering.load()) return 0;
    const int64_t remaining = impl_->next_recovery_retry_us.load() - esp_timer_get_time();
    if (remaining <= 0) return 0;
    return static_cast<uint32_t>((remaining + 999999) / 1000000);
}

size_t WifiProvisioningManager::scan(WifiNetworkInfo *networks, size_t capacity)
{
    if (impl_ == nullptr || networks == nullptr || capacity == 0) return 0;
    wifi_scan_config_t scan_config = {};
    scan_config.show_hidden = false;
    if (esp_wifi_scan_start(&scan_config, true) != ESP_OK) return 0;
    uint16_t available = 0;
    if (esp_wifi_scan_get_ap_num(&available) != ESP_OK || available == 0) return 0;
    constexpr uint16_t kMaximumScanRecords = 24;
    wifi_ap_record_t records[kMaximumScanRecords] = {};
    uint16_t count = std::min<uint16_t>(available, kMaximumScanRecords);
    if (esp_wifi_scan_get_ap_records(&count, records) != ESP_OK) return 0;
    std::sort(records, records + count,
              [](const wifi_ap_record_t &left, const wifi_ap_record_t &right) { return left.rssi > right.rssi; });

    size_t written = 0;
    for (uint16_t index = 0; index < count && written < capacity; ++index) {
        const char *ssid = reinterpret_cast<const char *>(records[index].ssid);
        if (ssid[0] == '\0') continue;
        bool duplicate = false;
        for (size_t prior = 0; prior < written; ++prior) {
            if (std::strcmp(networks[prior].ssid, ssid) == 0) {
                duplicate = true;
                break;
            }
        }
        if (duplicate) continue;
        copyText(networks[written].ssid, sizeof(networks[written].ssid), ssid);
        networks[written].rssi = records[index].rssi;
        networks[written].secure = records[index].authmode != WIFI_AUTH_OPEN;
        ++written;
    }
    ESP_LOGI(kTag, "Wi-Fi scan complete networks=%u", static_cast<unsigned>(written));
    return written;
}

bool WifiProvisioningManager::provision(const char *ssid, const char *password,
                                        char *message, size_t message_size)
{
    if (impl_ == nullptr || !impl_->provisioning.load()) {
        setMessage(message, message_size, "device is not in setup mode");
        return false;
    }
    if (!validCredentials(ssid, password)) {
        setMessage(message, message_size, "SSID must be 1-32 bytes; password must be empty or 8-63 bytes");
        return false;
    }

    impl_->provisioning_attempt.store(false);
    esp_wifi_disconnect();
    vTaskDelay(pdMS_TO_TICKS(100));
    wifi_config_t config = stationConfig(ssid, password);
    if (esp_wifi_set_config(WIFI_IF_STA, &config) != ESP_OK) {
        setMessage(message, message_size, "could not configure station");
        return false;
    }
    xEventGroupClearBits(impl_->events, kConnectedBit | kFailedBit);
    impl_->connected.store(false);
    impl_->retry_count.store(1);
    impl_->provisioning_attempt.store(true);
    ESP_LOGI(kTag, "testing provisioned SSID=%s", ssid);
    if (esp_wifi_connect() != ESP_OK) {
        impl_->provisioning_attempt.store(false);
        setMessage(message, message_size, "connection request failed");
        return false;
    }

    const EventBits_t bits = xEventGroupWaitBits(
        impl_->events, kConnectedBit | kFailedBit, pdFALSE, pdFALSE, kConnectionTimeout);
    impl_->provisioning_attempt.store(false);
    if ((bits & kConnectedBit) == 0) {
        ESP_LOGW(kTag, "provisioning connection failed SSID=%s", ssid);
        setMessage(message, message_size, "connection failed; check password and network availability");
        return false;
    }
    if (!saveCredentials(*impl_, ssid, password)) {
        ESP_LOGE(kTag, "connected but could not persist credentials");
        setMessage(message, message_size, "connected, but saving credentials failed");
        return false;
    }

    ESP_LOGI(kTag, "provisioning succeeded SSID=%s; credentials saved", ssid);
    setMessage(message, message_size, "connected and saved; device is restarting");
    scheduleRestart(*impl_);
    return true;
}

bool WifiProvisioningManager::forgetAndRestart(char *message, size_t message_size)
{
    if (impl_ == nullptr || !impl_->nvs_available) {
        setMessage(message, message_size, "credential storage unavailable");
        return false;
    }
    if (nvs_erase_all(impl_->nvs) != ESP_OK || nvs_commit(impl_->nvs) != ESP_OK) {
        setMessage(message, message_size, "could not clear saved credentials");
        return false;
    }
    impl_->saved_ssid[0] = '\0';
    impl_->saved_password[0] = '\0';
    ESP_LOGW(kTag, "saved Wi-Fi credentials cleared; restarting into setup mode");
    setMessage(message, message_size, "credentials cleared; device is restarting into setup mode");
    scheduleRestart(*impl_);
    return true;
}
