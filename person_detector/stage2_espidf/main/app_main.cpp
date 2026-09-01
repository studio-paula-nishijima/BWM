#include <array>
#include <memory>

#include "camera_source.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "motion_detector.h"
#include "activation_transport.h"
#include "person_detector.h"
#include "preview_server.h"
#include "stage2a_config.h"
#include "stage2b_config.h"
#include "trigger_zone_config.h"
#include "wifi_provisioning.h"

namespace {
constexpr char kTag[] = "bwm.stage2b";

template <size_t Window>
class RecentHits {
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
    std::array<bool, Window> hits_ = {};
    size_t next_ = 0;
    size_t count_ = 0;
    size_t hit_count_ = 0;
};

void logMemory(const char *phase)
{
    const size_t stack_low_water_bytes =
        static_cast<size_t>(uxTaskGetStackHighWaterMark(nullptr)) * sizeof(StackType_t);
    ESP_LOGI(kTag, "%s: free_heap_internal=%u free_psram=%u main_stack_low_water=%u bytes", phase,
             static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
             static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)),
             static_cast<unsigned>(stack_low_water_bytes));
}

void logPersonScan(const PersonDetection &detection, uint64_t total_scans,
                   const RecentHits<kRecentScanWindow> &recent, uint32_t scene_ms, uint32_t period_ms)
{
    const float region_inference_ms = detection.regions_scanned == 0 ? 0.0F :
        static_cast<float>(detection.inference_ms) / detection.regions_scanned;
    const float scene_hz = period_ms == 0 ? 0.0F : 1000.0F / period_ms;
    ESP_LOGI(kTag,
             "scan=%llu detection_mode=person inference_mode=%s person=%s boxes=%u "
             "recent_person_hits=%u/%u recent_ratio=%.2f regions=%u region_inference_ms=%.1f "
             "inference_ms=%u decode_ms=%u resize_ms=%u scene_ms=%u period_ms=%u scene_hz=%.2f",
             static_cast<unsigned long long>(total_scans), inferenceModeName(), detection.person ? "true" : "false",
             static_cast<unsigned>(detection.box_count), static_cast<unsigned>(recent.hits()),
             static_cast<unsigned>(recent.count()), recent.ratio(), detection.regions_scanned,
             region_inference_ms, detection.inference_ms, detection.decode_ms, detection.resize_ms,
             scene_ms, period_ms, scene_hz);

    for (size_t index = 0; index < detection.box_count; ++index) {
        const PersonBox &box = detection.boxes[index];
        ESP_LOGI(kTag, "person_box=%u confidence=%.3f x=%.3f y=%.3f w=%.3f h=%.3f area=%.4f",
                 static_cast<unsigned>(index), box.confidence, box.x, box.y, box.width, box.height,
                 box.width * box.height);
    }
}

void logMotionScan(const MotionDetection &detection, uint64_t total_scans,
                   uint32_t scene_ms, uint32_t period_ms)
{
    const float scene_hz = period_ms == 0 ? 0.0F : 1000.0F / period_ms;
    ESP_LOGI(kTag,
             "scan=%llu detection_mode=motion reference=%s motion=%s boxes=%u rejected_boxes=%u changed_pct=%.2f "
             "luma_shift=%.1f illumination_change=%s largest_blob_area=%.4f in_zone_hit=%s "
             "strong_in_zone=%s recent_hits=%u/%u confirmed=%s reason=%s decode_ms=%u processing_ms=%u scene_ms=%u "
             "period_ms=%u scene_hz=%.2f",
             static_cast<unsigned long long>(total_scans), detection.reference_ready ? "ready" : "learning",
             detection.motion ? "true" : "false", static_cast<unsigned>(detection.box_count),
             static_cast<unsigned>(detection.rejected_box_count),
             detection.changed_fraction * 100.0F, detection.global_luminance_shift,
             detection.illumination_change ? "true" : "false", detection.largest_blob_area,
             detection.in_zone_hit ? "true" : "false", detection.strong_in_zone_motion ? "true" : "false",
             static_cast<unsigned>(detection.recent_hits),
             static_cast<unsigned>(detection.recent_count), detection.confirmed ? "true" : "false",
             motionConfirmationReasonName(detection.confirmation_reason), detection.decode_ms,
             detection.processing_ms, scene_ms, period_ms, scene_hz);

    for (size_t index = 0; index < detection.box_count; ++index) {
        const MotionBox &box = detection.boxes[index];
        ESP_LOGI(kTag,
                 "motion_box=%u x=%.3f y=%.3f w=%.3f h=%.3f centre_x=%.3f centre_y=%.3f "
                 "area=%.4f mean_luma_change=%.1f mean_structure_change=%.1f strong=%s inside_zone=%s",
                 static_cast<unsigned>(index), box.x, box.y, box.width, box.height,
                 box.centre_x, box.centre_y, box.area_fraction, box.mean_luminance_change,
                 box.mean_structure_change, box.strong_motion ? "true" : "false",
                 box.inside_trigger_zone ? "true" : "false");
    }
    for (size_t index = 0; index < detection.rejected_box_count; ++index) {
        const MotionBox &box = detection.rejected_boxes[index];
        ESP_LOGI(kTag,
                 "shadow_box=%u x=%.3f y=%.3f w=%.3f h=%.3f area=%.4f mean_luma_change=%.1f "
                 "mean_structure_change=%.1f inside_zone=%s likely_shadow=true",
                 static_cast<unsigned>(index), box.x, box.y, box.width, box.height, box.area_fraction,
                 box.mean_luminance_change, box.mean_structure_change,
                 box.inside_trigger_zone ? "true" : "false");
    }
}
}  // namespace

extern "C" void app_main(void)
{
    ESP_LOGI(kTag, "BWM Vision Node - P2 automatic activation-transport fallback");
    ESP_LOGI(kTag, "detection_mode=%s camera=%ux%u format=JPEG", detectionModeName(),
             static_cast<unsigned>(sourceFrameWidth()), static_cast<unsigned>(sourceFrameHeight()));
    if (motionModeEnabled()) {
        ESP_LOGI(kTag,
                 "motion grid=%ux%u threshold=%u confirmation=%u-of-%u "
                 "strong=(area>=%.3f luma>=%.1f structure>=%.1f box<=%.2f) shadow_structure<%.1f",
                 static_cast<unsigned>(kMotionGridWidth), static_cast<unsigned>(kMotionGridHeight),
                 static_cast<unsigned>(kMotionPixelDifferenceThreshold),
                 static_cast<unsigned>(kMotionConfirmationHits),
                 static_cast<unsigned>(kMotionConfirmationWindow), kStrongMotionMinimumChangedFraction,
                 kStrongMotionMinimumLuminanceChange, kStrongMotionMinimumStructureChange,
                 kStrongMotionMaximumBoxFraction, kMotionMinimumStructureChange);
    } else {
        ESP_LOGI(kTag,
                 "person model=PICO_S8_V1 ESP-DL input=224x224 inference_mode=%s regions=%ux%u overlap=%.0f%%",
                 inferenceModeName(), static_cast<unsigned>(tiledModeEnabled() ? kTileColumns : 1),
                 static_cast<unsigned>(tiledModeEnabled() ? kTileRows : 1), kTileOverlap * 100.0F);
    }
    logMemory("before camera/detector");

    TriggerZoneConfig trigger_zone;
    if (!trigger_zone.begin()) {
        ESP_LOGE(kTag, "trigger-zone configuration setup failed");
        return;
    }
    const NormalisedZone initial_zone = trigger_zone.current();
    ESP_LOGI(kTag, "active trigger zone x=%.3f y=%.3f w=%.3f h=%.3f",
             initial_zone.x, initial_zone.y, initial_zone.width, initial_zone.height);

    CameraSource camera;
    if (!camera.initialise()) {
        ESP_LOGE(kTag, "camera setup failed; not starting detector");
        return;
    }

    const size_t detector_psram_before = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    std::unique_ptr<PersonDetector> person_detector;
    std::unique_ptr<MotionDetector> motion_detector;
    if (motionModeEnabled()) {
        motion_detector = std::make_unique<MotionDetector>();
        if (!motion_detector->initialise(sourceFrameWidth(), sourceFrameHeight())) {
            ESP_LOGE(kTag, "motion detector setup failed; not starting detection");
            return;
        }
    } else {
        person_detector = std::make_unique<EspDlPedestrianDetector>();
        if (!person_detector->initialise(sourceFrameWidth(), sourceFrameHeight())) {
            ESP_LOGE(kTag, "person detector setup failed; not starting inference");
            return;
        }
    }
    const size_t detector_psram_after = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    ESP_LOGI(kTag, "selected detector PSRAM delta=%d bytes",
             static_cast<int>(detector_psram_before) - static_cast<int>(detector_psram_after));

    RecentHits<kRecentScanWindow> recent_person;
    RecentHits<kMotionConfirmationWindow> recent_motion;
    ActivationTransport activation_transport;
    WifiProvisioningManager wifi;
    if (!wifi.begin()) {
        ESP_LOGE(kTag, "Wi-Fi provisioning setup failed; detection continues locally");
    }
    PreviewServer preview;
    // The browser remains available on the station or temporary setup AP.
    // MQTT shares the station connection and retains its existing semantics.
    preview.begin(trigger_zone, activation_transport, wifi);
    activation_transport.begin();
    activation_transport.updateNetworkHealth(
        wifi.connected(), static_cast<uint64_t>(esp_timer_get_time() / 1000));
    logMemory("after camera/detector/preview");
    uint64_t total_scans = 0;
    int64_t previous_scan_started_us = 0;
    bool previous_motion_confirmation = false;
    while (true) {
        const int64_t scan_started_us = esp_timer_get_time();
        activation_transport.updateNetworkHealth(
            wifi.connected(), static_cast<uint64_t>(scan_started_us / 1000));
        const uint32_t period_ms = previous_scan_started_us == 0 ? 0 :
            static_cast<uint32_t>((scan_started_us - previous_scan_started_us) / 1000);
        previous_scan_started_us = scan_started_us;

        camera_fb_t *frame = camera.capture();
        if (frame == nullptr) {
            ESP_LOGE(kTag, "camera frame capture failed");
        } else {
            preview.publishFrame(*frame);
            ++total_scans;
            if (motionModeEnabled()) {
                MotionDetection detection = motion_detector->detect(*frame, trigger_zone.current());
                camera.release(frame);
                recent_motion.add(detection.reference_ready && detection.in_zone_hit &&
                                  !detection.illumination_change);
                detection.recent_hits = recent_motion.hits();
                detection.recent_count = recent_motion.count();
                if (detection.illumination_change) {
                    detection.confirmation_reason = MotionConfirmationReason::RejectedGlobalIllumination;
                } else if (detection.strong_in_zone_motion) {
                    detection.confirmed = true;
                    detection.confirmation_reason = MotionConfirmationReason::StrongImmediate;
                } else if (recent_motion.hits() >= kMotionConfirmationHits) {
                    detection.confirmed = true;
                    detection.confirmation_reason = MotionConfirmationReason::NOfM;
                } else if (detection.in_zone_hit) {
                    detection.confirmation_reason = MotionConfirmationReason::AwaitingNOfM;
                } else if (detection.rejected_box_count > 0) {
                    detection.confirmation_reason = MotionConfirmationReason::RejectedShadow;
                } else if (detection.reference_ready && detection.changed_fraction > 0.0F) {
                    detection.confirmation_reason = MotionConfirmationReason::RejectedNoise;
                }
                preview.publishMotionDetection(detection);
                activation_transport.publishStateIfChanged(detection.confirmed);
                const uint32_t scene_ms = static_cast<uint32_t>((esp_timer_get_time() - scan_started_us) / 1000);
                logMotionScan(detection, total_scans, scene_ms, period_ms);
                if (detection.confirmed && !previous_motion_confirmation) {
                    ESP_LOGW(kTag, "MOTION TRIGGER confirmed reason=%s (%u-of-%u in-zone scans)",
                             motionConfirmationReasonName(detection.confirmation_reason),
                             static_cast<unsigned>(recent_motion.hits()),
                             static_cast<unsigned>(kMotionConfirmationWindow));
                }
                previous_motion_confirmation = detection.confirmed;
            } else {
                const PersonDetection detection = person_detector->detect(*frame);
                camera.release(frame);
                preview.publishPersonDetection(detection);
                recent_person.add(detection.person);
                activation_transport.publishStateIfChanged(detection.person);
                const uint32_t scene_ms = static_cast<uint32_t>((esp_timer_get_time() - scan_started_us) / 1000);
                logPersonScan(detection, total_scans, recent_person, scene_ms, period_ms);
            }
        }

        if (total_scans > 0 && total_scans % kMotionMemoryLogEveryScans == 0) {
            logMemory("periodic");
        }
        const int64_t elapsed_ms = (esp_timer_get_time() - scan_started_us) / 1000;
        const int64_t remaining_ms = static_cast<int64_t>(kMinimumSceneIntervalMs) - elapsed_ms;
        if (remaining_ms > 0) {
            vTaskDelay(pdMS_TO_TICKS(remaining_ms));
        } else {
            // Always let CPU 0's idle task service its watchdog after a long scan.
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
}
