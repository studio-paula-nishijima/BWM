#include <memory>

#include "camera_source.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "person_detector.h"
#include "preview_server.h"

namespace {
constexpr char kTag[] = "bwm.stage2";
constexpr TickType_t kInferenceInterval = pdMS_TO_TICKS(500);

void logDetection(const PersonDetection &detection)
{
    if (!detection.person) {
        ESP_LOGI(kTag, "person=false inference_ms=%u", detection.inference_ms);
        return;
    }
    ESP_LOGI(kTag,
             "person=true confidence=%.3f x=%.3f y=%.3f w=%.3f h=%.3f inference_ms=%u",
             detection.confidence, detection.x, detection.y, detection.width, detection.height,
             detection.inference_ms);
}
}  // namespace

extern "C" void app_main(void)
{
    ESP_LOGI(kTag, "BWM Vision Node — Stage 2 person detection");

    CameraSource camera;
    if (!camera.initialise()) {
        ESP_LOGE(kTag, "camera setup failed; not starting detector");
        return;
    }

    std::unique_ptr<PersonDetector> detector = std::make_unique<EspDlPedestrianDetector>();
    if (!detector->initialise(320, 240)) {
        ESP_LOGE(kTag, "detector setup failed; not starting inference");
        return;
    }

    PreviewServer preview;
    preview.begin();

    while (true) {
        const int64_t frame_started_us = esp_timer_get_time();
        camera_fb_t *frame = camera.capture();
        if (frame == nullptr) {
            ESP_LOGE(kTag, "camera frame capture failed");
        } else {
            preview.publishFrame(*frame);
            const PersonDetection detection = detector->detect(*frame);
            camera.release(frame);
            preview.publishDetection(detection);
            logDetection(detection);
        }

        const int64_t elapsed_ms = (esp_timer_get_time() - frame_started_us) / 1000;
        const int64_t remaining_ms = 500 - elapsed_ms;
        if (remaining_ms > 0) {
            vTaskDelay(pdMS_TO_TICKS(remaining_ms));
        }
    }
}
