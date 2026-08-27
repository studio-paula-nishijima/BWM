#include "trigger_zone_config.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <new>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "nvs.h"
#include "nvs_flash.h"

namespace {
constexpr char kTag[] = "bwm.zone";
constexpr char kNamespace[] = "bwm_config";
constexpr char kZoneKey[] = "trigger_zone";
constexpr uint32_t kStoredMagic = 0x42574d5a;
constexpr uint16_t kRectangleVersion = 1;
constexpr uint16_t kPolygonVersion = 2;
constexpr size_t kMaximumLegacyPolygonVertices = 8;

struct StoredRectangleV1 {
    uint32_t magic;
    uint16_t version;
    uint16_t size;
    float x;
    float y;
    float width;
    float height;
    uint32_t checksum;
};

struct StoredPointV2 {
    float x;
    float y;
};

// Retained only to recover a rectangle if Stage 3B was saved before rollback.
struct StoredGeometryV2 {
    uint32_t magic;
    uint16_t version;
    uint16_t size;
    uint8_t inclusion_count;
    uint8_t exclusion_count;
    uint8_t exclusion_enabled;
    uint8_t reserved;
    StoredPointV2 inclusion[kMaximumLegacyPolygonVertices];
    StoredPointV2 exclusion[kMaximumLegacyPolygonVertices];
    uint32_t checksum;
};

uint32_t checksumBytes(const void *value, size_t length)
{
    const auto *bytes = static_cast<const uint8_t *>(value);
    uint32_t hash = 2166136261U;
    for (size_t index = 0; index < length; ++index) hash = (hash ^ bytes[index]) * 16777619U;
    return hash;
}

template <typename Stored>
uint32_t storedChecksum(const Stored &stored)
{
    return checksumBytes(&stored, offsetof(Stored, checksum));
}

bool polygonBoundingRectangle(const StoredGeometryV2 &stored, NormalisedZone &zone)
{
    if (stored.inclusion_count < 3 || stored.inclusion_count > kMaximumLegacyPolygonVertices) return false;
    float min_x = 1.0F;
    float min_y = 1.0F;
    float max_x = 0.0F;
    float max_y = 0.0F;
    for (size_t index = 0; index < stored.inclusion_count; ++index) {
        const StoredPointV2 &point = stored.inclusion[index];
        if (!std::isfinite(point.x) || !std::isfinite(point.y) ||
            point.x < 0.0F || point.x > 1.0F || point.y < 0.0F || point.y > 1.0F) return false;
        min_x = std::min(min_x, point.x);
        min_y = std::min(min_y, point.y);
        max_x = std::max(max_x, point.x);
        max_y = std::max(max_y, point.y);
    }
    zone = {min_x, min_y, max_x - min_x, max_y - min_y};
    return TriggerZoneConfig::valid(zone);
}
}  // namespace

class TriggerZoneConfig::Impl {
public:
    mutable SemaphoreHandle_t mutex = nullptr;
    nvs_handle_t nvs = 0;
    bool nvs_available = false;
    NormalisedZone zone = kDefaultMotionTriggerZone;
};

TriggerZoneConfig::~TriggerZoneConfig()
{
    if (impl_ == nullptr) return;
    if (impl_->nvs_available) nvs_close(impl_->nvs);
    if (impl_->mutex != nullptr) vSemaphoreDelete(impl_->mutex);
    delete impl_;
}

bool TriggerZoneConfig::valid(const NormalisedZone &zone)
{
    return std::isfinite(zone.x) && std::isfinite(zone.y) &&
           std::isfinite(zone.width) && std::isfinite(zone.height) &&
           zone.x >= 0.0F && zone.y >= 0.0F &&
           zone.width >= kMinimumTriggerZoneSize && zone.height >= kMinimumTriggerZoneSize &&
           zone.x + zone.width <= 1.0F && zone.y + zone.height <= 1.0F;
}

bool TriggerZoneConfig::begin()
{
    impl_ = new (std::nothrow) Impl();
    if (impl_ == nullptr) return false;
    impl_->mutex = xSemaphoreCreateMutex();
    if (impl_->mutex == nullptr) return false;

    const esp_err_t init_result = nvs_flash_init();
    if (init_result != ESP_OK) {
        ESP_LOGW(kTag, "NVS unavailable (%s); using runtime defaults", esp_err_to_name(init_result));
        return true;
    }
    const esp_err_t open_result = nvs_open(kNamespace, NVS_READWRITE, &impl_->nvs);
    if (open_result != ESP_OK) {
        ESP_LOGW(kTag, "could not open NVS namespace (%s); using runtime defaults", esp_err_to_name(open_result));
        return true;
    }
    impl_->nvs_available = true;

    size_t stored_size = 0;
    const esp_err_t size_result = nvs_get_blob(impl_->nvs, kZoneKey, nullptr, &stored_size);
    if (size_result == ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGI(kTag, "no saved trigger zone; using default");
        return true;
    }
    if (size_result != ESP_OK) {
        ESP_LOGW(kTag, "could not read saved trigger zone (%s); using default", esp_err_to_name(size_result));
        return true;
    }

    if (stored_size == sizeof(StoredRectangleV1)) {
        StoredRectangleV1 stored = {};
        size_t read_size = sizeof(stored);
        const esp_err_t result = nvs_get_blob(impl_->nvs, kZoneKey, &stored, &read_size);
        const NormalisedZone loaded{stored.x, stored.y, stored.width, stored.height};
        if (result == ESP_OK && stored.magic == kStoredMagic && stored.version == kRectangleVersion &&
            stored.size == sizeof(stored) && stored.checksum == storedChecksum(stored) && valid(loaded)) {
            impl_->zone = loaded;
            ESP_LOGI(kTag, "loaded rectangle x=%.3f y=%.3f w=%.3f h=%.3f",
                     loaded.x, loaded.y, loaded.width, loaded.height);
            return true;
        }
    } else if (stored_size == sizeof(StoredGeometryV2)) {
        StoredGeometryV2 stored = {};
        size_t read_size = sizeof(stored);
        const esp_err_t result = nvs_get_blob(impl_->nvs, kZoneKey, &stored, &read_size);
        NormalisedZone recovered = {};
        if (result == ESP_OK && stored.magic == kStoredMagic && stored.version == kPolygonVersion &&
            stored.size == sizeof(stored) && stored.checksum == storedChecksum(stored) &&
            polygonBoundingRectangle(stored, recovered)) {
            impl_->zone = recovered;
            ESP_LOGI(kTag, "converted saved Stage 3B inclusion polygon to bounding rectangle; Save writes v1");
            return true;
        }
    }

    ESP_LOGW(kTag, "saved trigger zone is corrupt or invalid; using default");
    return true;
}

NormalisedZone TriggerZoneConfig::current() const
{
    if (impl_ == nullptr || impl_->mutex == nullptr) return kDefaultMotionTriggerZone;
    NormalisedZone result = kDefaultMotionTriggerZone;
    if (xSemaphoreTake(impl_->mutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        result = impl_->zone;
        xSemaphoreGive(impl_->mutex);
    }
    return result;
}

bool TriggerZoneConfig::apply(const NormalisedZone &zone)
{
    if (!valid(zone) || impl_ == nullptr || impl_->mutex == nullptr) return false;
    if (xSemaphoreTake(impl_->mutex, pdMS_TO_TICKS(100)) != pdTRUE) return false;
    impl_->zone = zone;
    xSemaphoreGive(impl_->mutex);
    ESP_LOGI(kTag, "applied rectangle x=%.3f y=%.3f w=%.3f h=%.3f",
             zone.x, zone.y, zone.width, zone.height);
    return true;
}

bool TriggerZoneConfig::save()
{
    if (impl_ == nullptr || !impl_->nvs_available) {
        ESP_LOGW(kTag, "cannot save trigger zone: NVS unavailable");
        return false;
    }
    const NormalisedZone zone = current();
    StoredRectangleV1 stored = {kStoredMagic, kRectangleVersion, sizeof(StoredRectangleV1),
                                zone.x, zone.y, zone.width, zone.height, 0};
    stored.checksum = storedChecksum(stored);
    esp_err_t result = nvs_set_blob(impl_->nvs, kZoneKey, &stored, sizeof(stored));
    if (result == ESP_OK) result = nvs_commit(impl_->nvs);
    if (result != ESP_OK) {
        ESP_LOGW(kTag, "failed to save trigger zone: %s", esp_err_to_name(result));
        return false;
    }
    ESP_LOGI(kTag, "saved rectangle trigger zone to NVS");
    return true;
}

void TriggerZoneConfig::resetToDefault()
{
    apply(kDefaultMotionTriggerZone);
}
