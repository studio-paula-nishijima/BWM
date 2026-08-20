#include <array>
#include <memory>

#include "camera_source.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "person_detector.h"
#include "mqtt_activation_publisher.h"
#include "preview_server.h"
#include "stage2a_config.h"

namespace {
constexpr char kTag[] = "bwm.stage2a";

class RecentDetections {
public:
    void add(bool detected)
    {
        if (count_ == hits_.size()) {
            if (hits_[next_]) --hit_count_;
        } else {
            ++count_;
        }
        hits_[next_] = detected;
        if (detected) ++hit_count_;
        next_ = (next_ + 1) % hits_.size();
    }

    size_t hits() const { return hit_count_; }
    size_t count() const { return count_; }
    float ratio() const { return count_ == 0 ? 0.0F : static_cast<float>(hit_count_) / count_; }

private:
    std::array<bool, kRecentScanWindow> hits_ = {};
    size_t next_ = 0;
    size_t count_ = 0;
    size_t hit_count_ = 0;
};

void logScan(const PersonDetection &detection, uint64_t total_scans,
             const RecentDetections &recent, uint32_t scene_ms, uint32_t period_ms)
{
    const float region_inference_ms = detection.regions_scanned == 0 ? 0.0F :
        static_cast<float>(detection.inference_ms) / detection.regions_scanned;
    const float scene_hz = period_ms == 0 ? 0.0F : 1000.0F / period_ms;
    ESP_LOGI(kTag,
             "scan=%llu mode=%s person=%s boxes=%u recent_person_hits=%u/%u recent_ratio=%.2f "
             "regions=%u region_inference_ms=%.1f inference_ms=%u decode_ms=%u resize_ms=%u "
             "scene_ms=%u period_ms=%u scene_hz=%.2f",
             static_cast<unsigned long long>(total_scans), inferenceModeName(), detection.person ? "true" : "false",
             static_cast<unsigned>(detection.box_count), static_cast<unsigned>(recent.hits()),
             static_cast<unsigned>(recent.count()), recent.ratio(), detection.regions_scanned,
             region_inference_ms, detection.inference_ms, detection.decode_ms, detection.resize_ms,
             scene_ms, period_ms, scene_hz);

    for (size_t index = 0; index < detection.box_count; ++index) {
        const PersonBox &box = detection.boxes[index];
        ESP_LOGI(kTag,
                 "detection=%u confidence=%.3f x=%.3f y=%.3f w=%.3f h=%.3f area=%.4f inference_ms=%u",
                 static_cast<unsigned>(index), box.confidence, box.x, box.y, box.width, box.height,
                 box.width * box.height, detection.inference_ms);
    }
}
}  // namespace

extern "C" void app_main(void)
{
    ESP_LOGI(kTag, "BWM Vision Node - Stage 2A robustness diagnostics");
    ESP_LOGI(kTag,
             "baseline/model: camera=%ux%u JPEG model=PICO_S8_V1 ESP-DL input=224x224 mode=%s; "
             "full_frame uses entire frame, tiled uses %ux%u regions with %.0f%% overlap",
             static_cast<unsigned>(sourceFrameWidth()), static_cast<unsigned>(sourceFrameHeight()),
             inferenceModeName(), static_cast<unsigned>(kTileColumns), static_cast<unsigned>(kTileRows),
             kTileOverlap * 100.0F);
    ESP_LOGI(kTag, "PSRAM free before camera/model: %u bytes",
             static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));

    CameraSource camera;
    if (!camera.initialise()) {
        ESP_LOGE(kTag, "camera setup failed; not starting detector");
        return;
    }

    std::unique_ptr<PersonDetector> detector = std::make_unique<EspDlPedestrianDetector>();
    if (!detector->initialise(sourceFrameWidth(), sourceFrameHeight())) {
        ESP_LOGE(kTag, "detector setup failed; not starting inference");
        return;
    }

    PreviewServer preview;
    preview.begin();
    ESP_LOGI(kTag, "PSRAM free after camera/model/preview: %u bytes",
             static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));

    RecentDetections recent;
    MqttActivationPublisher mqtt_activation;
    mqtt_activation.begin();
    uint64_t total_scans = 0;
    int64_t previous_scan_started_us = 0;
    while (true) {
        const int64_t scan_started_us = esp_timer_get_time();
        const uint32_t period_ms = previous_scan_started_us == 0 ? 0 :
            static_cast<uint32_t>((scan_started_us - previous_scan_started_us) / 1000);
        previous_scan_started_us = scan_started_us;

        camera_fb_t *frame = camera.capture();
        if (frame == nullptr) {
            ESP_LOGE(kTag, "camera frame capture failed");
        } else {
            preview.publishFrame(*frame);
            const PersonDetection detection = detector->detect(*frame);
            camera.release(frame);
            preview.publishDetection(detection);
            ++total_scans;
            recent.add(detection.person);
            // The detector continues to own this boolean decision. The adapter
            // emits an explicit semantic state only when it changes.
            mqtt_activation.publishStateIfChanged(detection.person);
            const uint32_t scene_ms = static_cast<uint32_t>((esp_timer_get_time() - scan_started_us) / 1000);
            logScan(detection, total_scans, recent, scene_ms, period_ms);
        }

        const int64_t elapsed_ms = (esp_timer_get_time() - scan_started_us) / 1000;
        const int64_t remaining_ms = static_cast<int64_t>(kMinimumSceneIntervalMs) - elapsed_ms;
        if (remaining_ms > 0) vTaskDelay(pdMS_TO_TICKS(remaining_ms));
    }
}
