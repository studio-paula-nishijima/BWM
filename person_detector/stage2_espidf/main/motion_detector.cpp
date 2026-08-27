#include "motion_detector.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <new>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "img_converters.h"

namespace {
constexpr char kTag[] = "bwm.motion";
constexpr size_t kGridPixels = static_cast<size_t>(kMotionGridWidth) * kMotionGridHeight;

bool centreInsideTriggerZone(float x, float y, const NormalisedZone &zone)
{
    return x >= zone.x && x <= zone.x + zone.width &&
           y >= zone.y && y <= zone.y + zone.height;
}

uint16_t gradientMagnitude(const uint8_t *image, uint16_t x, uint16_t y)
{
    if (x == 0 || y == 0 || x + 1 >= kMotionGridWidth || y + 1 >= kMotionGridHeight) return 0;
    const size_t index = static_cast<size_t>(y) * kMotionGridWidth + x;
    return static_cast<uint16_t>(
        std::abs(static_cast<int>(image[index + 1]) - image[index - 1]) +
        std::abs(static_cast<int>(image[index + kMotionGridWidth]) - image[index - kMotionGridWidth]));
}
}  // namespace

const char *motionConfirmationReasonName(MotionConfirmationReason reason)
{
    switch (reason) {
        case MotionConfirmationReason::StrongImmediate: return "strong_immediate";
        case MotionConfirmationReason::NOfM: return "n_of_m";
        case MotionConfirmationReason::AwaitingNOfM: return "awaiting_n_of_m";
        case MotionConfirmationReason::RejectedShadow: return "rejected_shadow";
        case MotionConfirmationReason::RejectedGlobalIllumination: return "rejected_global_illumination";
        case MotionConfirmationReason::RejectedNoise: return "rejected_noise";
        default: return "none";
    }
}

class MotionDetector::Impl {
public:
    uint16_t source_width = 0;
    uint16_t source_height = 0;
    uint8_t *rgb888 = nullptr;
    uint8_t *previous = nullptr;
    uint8_t *current = nullptr;
    uint8_t *changed = nullptr;
    uint8_t *filtered = nullptr;
    uint16_t *queue = nullptr;
    bool has_reference = false;
};

MotionDetector::~MotionDetector()
{
    if (impl_ == nullptr) return;
    heap_caps_free(impl_->queue);
    heap_caps_free(impl_->filtered);
    heap_caps_free(impl_->changed);
    heap_caps_free(impl_->current);
    heap_caps_free(impl_->previous);
    heap_caps_free(impl_->rgb888);
    delete impl_;
}

size_t MotionDetector::workspaceBytes() const
{
    if (impl_ == nullptr) return 0;
    return static_cast<size_t>(impl_->source_width) * impl_->source_height * 3 +
           kGridPixels * 4 + kGridPixels * sizeof(uint16_t);
}

bool MotionDetector::initialise(uint16_t source_width, uint16_t source_height)
{
    impl_ = new (std::nothrow) Impl();
    if (impl_ == nullptr) return false;
    impl_->source_width = source_width;
    impl_->source_height = source_height;
    const size_t rgb_bytes = static_cast<size_t>(source_width) * source_height * 3;
    impl_->rgb888 = static_cast<uint8_t *>(heap_caps_malloc(rgb_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    impl_->previous = static_cast<uint8_t *>(heap_caps_malloc(kGridPixels, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    impl_->current = static_cast<uint8_t *>(heap_caps_malloc(kGridPixels, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    impl_->changed = static_cast<uint8_t *>(heap_caps_malloc(kGridPixels, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    impl_->filtered = static_cast<uint8_t *>(heap_caps_malloc(kGridPixels, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    impl_->queue = static_cast<uint16_t *>(heap_caps_malloc(kGridPixels * sizeof(uint16_t),
                                                            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (impl_->rgb888 == nullptr || impl_->previous == nullptr || impl_->current == nullptr ||
        impl_->changed == nullptr || impl_->filtered == nullptr || impl_->queue == nullptr) {
        ESP_LOGE(kTag, "PSRAM workspace allocation failed");
        return false;
    }
    ESP_LOGI(kTag,
             "motion detector ready: source=%ux%u JPEG grid=%ux%u threshold=%u min_blob=%u workspace=%u bytes",
             static_cast<unsigned>(source_width), static_cast<unsigned>(source_height),
             static_cast<unsigned>(kMotionGridWidth), static_cast<unsigned>(kMotionGridHeight),
             static_cast<unsigned>(kMotionPixelDifferenceThreshold),
             static_cast<unsigned>(kMotionMinimumBlobPixels), static_cast<unsigned>(workspaceBytes()));
    return true;
}

MotionDetection MotionDetector::detect(const camera_fb_t &jpeg_frame, const NormalisedZone &trigger_zone)
{
    MotionDetection output;
    if (impl_ == nullptr || jpeg_frame.format != PIXFORMAT_JPEG ||
        jpeg_frame.width != impl_->source_width || jpeg_frame.height != impl_->source_height) {
        return output;
    }

    const int64_t decode_started = esp_timer_get_time();
    if (!fmt2rgb888(jpeg_frame.buf, jpeg_frame.len, jpeg_frame.format, impl_->rgb888)) {
        ESP_LOGE(kTag, "JPEG to RGB888 conversion failed");
        return output;
    }
    output.decode_ms = static_cast<uint32_t>((esp_timer_get_time() - decode_started) / 1000);
    const int64_t processing_started = esp_timer_get_time();

    uint32_t current_luminance_sum = 0;
    const uint16_t cell_width = impl_->source_width / kMotionGridWidth;
    const uint16_t cell_height = impl_->source_height / kMotionGridHeight;
    for (uint16_t gy = 0; gy < kMotionGridHeight; ++gy) {
        for (uint16_t gx = 0; gx < kMotionGridWidth; ++gx) {
            uint32_t luminance_sum = 0;
            for (uint16_t sy = 0; sy < cell_height; ++sy) {
                const uint16_t y = gy * cell_height + sy;
                for (uint16_t sx = 0; sx < cell_width; ++sx) {
                    const uint16_t x = gx * cell_width + sx;
                    const size_t offset = (static_cast<size_t>(y) * impl_->source_width + x) * 3;
                    const uint8_t r = impl_->rgb888[offset];
                    const uint8_t g = impl_->rgb888[offset + 1];
                    const uint8_t b = impl_->rgb888[offset + 2];
                    luminance_sum += (77U * r + 150U * g + 29U * b) >> 8;
                }
            }
            const size_t index = static_cast<size_t>(gy) * kMotionGridWidth + gx;
            impl_->current[index] = static_cast<uint8_t>(luminance_sum / (cell_width * cell_height));
            current_luminance_sum += impl_->current[index];
        }
    }

    if (!impl_->has_reference) {
        std::memcpy(impl_->previous, impl_->current, kGridPixels);
        impl_->has_reference = true;
        output.processing_ms = static_cast<uint32_t>((esp_timer_get_time() - processing_started) / 1000);
        return output;
    }
    output.reference_ready = true;

    uint32_t previous_luminance_sum = 0;
    size_t changed_pixels = 0;
    for (size_t index = 0; index < kGridPixels; ++index) {
        previous_luminance_sum += impl_->previous[index];
        const int difference = std::abs(static_cast<int>(impl_->current[index]) - impl_->previous[index]);
        impl_->changed[index] = difference >= kMotionPixelDifferenceThreshold ? 1 : 0;
        changed_pixels += impl_->changed[index];
    }
    output.changed_fraction = static_cast<float>(changed_pixels) / kGridPixels;
    output.global_luminance_shift = std::fabs(static_cast<float>(current_luminance_sum) / kGridPixels -
                                               static_cast<float>(previous_luminance_sum) / kGridPixels);
    output.illumination_change = output.changed_fraction >= kMotionGlobalChangedFraction ||
        (output.global_luminance_shift >= kMotionLargeLuminanceShift &&
         output.changed_fraction >= kMotionLuminanceChangedFraction);

    std::memset(impl_->filtered, 0, kGridPixels);
    if (!output.illumination_change) {
        for (uint16_t y = 1; y + 1 < kMotionGridHeight; ++y) {
            for (uint16_t x = 1; x + 1 < kMotionGridWidth; ++x) {
                size_t neighbours = 0;
                for (int dy = -1; dy <= 1; ++dy) {
                    for (int dx = -1; dx <= 1; ++dx) {
                        neighbours += impl_->changed[static_cast<size_t>(y + dy) * kMotionGridWidth + x + dx];
                    }
                }
                if (neighbours >= kMotionNeighbourThreshold) {
                    impl_->filtered[static_cast<size_t>(y) * kMotionGridWidth + x] = 1;
                }
            }
        }

        for (uint16_t start_y = 0; start_y < kMotionGridHeight; ++start_y) {
            for (uint16_t start_x = 0; start_x < kMotionGridWidth; ++start_x) {
                const uint16_t start = start_y * kMotionGridWidth + start_x;
                if (impl_->filtered[start] == 0) continue;
                size_t head = 0;
                size_t tail = 0;
                impl_->queue[tail++] = start;
                impl_->filtered[start] = 0;
                uint16_t min_x = start_x;
                uint16_t max_x = start_x;
                uint16_t min_y = start_y;
                uint16_t max_y = start_y;
                size_t pixels = 0;
                uint32_t luminance_change_sum = 0;
                uint32_t structure_change_sum = 0;
                while (head < tail) {
                    const uint16_t index = impl_->queue[head++];
                    const uint16_t x = index % kMotionGridWidth;
                    const uint16_t y = index / kMotionGridWidth;
                    ++pixels;
                    luminance_change_sum += std::abs(static_cast<int>(impl_->current[index]) - impl_->previous[index]);
                    const uint16_t current_gradient = gradientMagnitude(impl_->current, x, y);
                    const uint16_t previous_gradient = gradientMagnitude(impl_->previous, x, y);
                    structure_change_sum += std::abs(static_cast<int>(current_gradient) - previous_gradient);
                    min_x = std::min(min_x, x);
                    max_x = std::max(max_x, x);
                    min_y = std::min(min_y, y);
                    max_y = std::max(max_y, y);
                    for (int dy = -1; dy <= 1; ++dy) {
                        for (int dx = -1; dx <= 1; ++dx) {
                            if (dx == 0 && dy == 0) continue;
                            const int nx = static_cast<int>(x) + dx;
                            const int ny = static_cast<int>(y) + dy;
                            if (nx < 0 || ny < 0 || nx >= kMotionGridWidth || ny >= kMotionGridHeight) continue;
                            const uint16_t neighbour = static_cast<uint16_t>(ny * kMotionGridWidth + nx);
                            if (impl_->filtered[neighbour] == 0) continue;
                            impl_->filtered[neighbour] = 0;
                            impl_->queue[tail++] = neighbour;
                        }
                    }
                }
                const float pixel_area = static_cast<float>(pixels) / kGridPixels;
                output.largest_blob_area = std::max(output.largest_blob_area, pixel_area);
                if (pixels < kMotionMinimumBlobPixels) continue;
                MotionBox box;
                box.x = static_cast<float>(min_x) / kMotionGridWidth;
                box.y = static_cast<float>(min_y) / kMotionGridHeight;
                box.width = static_cast<float>(max_x - min_x + 1) / kMotionGridWidth;
                box.height = static_cast<float>(max_y - min_y + 1) / kMotionGridHeight;
                box.centre_x = box.x + box.width * 0.5F;
                box.centre_y = box.y + box.height * 0.5F;
                box.area_fraction = pixel_area;
                box.mean_luminance_change = static_cast<float>(luminance_change_sum) / pixels;
                box.mean_structure_change = static_cast<float>(structure_change_sum) / pixels;
                box.inside_trigger_zone = centreInsideTriggerZone(
                    box.centre_x, box.centre_y, trigger_zone);
                box.likely_shadow = box.mean_luminance_change >= kMotionShadowMinimumLuminanceChange &&
                    box.mean_structure_change < kMotionMinimumStructureChange;
                const float bounding_area = box.width * box.height;
                box.strong_motion = !box.likely_shadow &&
                    box.area_fraction >= kStrongMotionMinimumChangedFraction &&
                    box.mean_luminance_change >= kStrongMotionMinimumLuminanceChange &&
                    box.mean_structure_change >= kStrongMotionMinimumStructureChange &&
                    bounding_area <= kStrongMotionMaximumBoxFraction;
                if (box.likely_shadow) {
                    if (output.rejected_box_count < output.rejected_boxes.size()) {
                        output.rejected_boxes[output.rejected_box_count++] = box;
                    }
                    continue;
                }
                if (output.box_count == output.boxes.size()) continue;
                output.boxes[output.box_count++] = box;
                output.in_zone_hit = output.in_zone_hit || box.inside_trigger_zone;
                output.strong_in_zone_motion = output.strong_in_zone_motion ||
                    (box.inside_trigger_zone && box.strong_motion);
            }
        }
    }

    output.motion = output.box_count > 0;
    std::memcpy(impl_->previous, impl_->current, kGridPixels);
    output.processing_ms = static_cast<uint32_t>((esp_timer_get_time() - processing_started) / 1000);
    return output;
}
