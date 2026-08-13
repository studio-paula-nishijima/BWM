#include "person_detector.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <new>

#include "dl_image_define.hpp"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "img_converters.h"
#include "pedestrian_detect.hpp"
#include "stage2a_config.h"

namespace {
constexpr char kTag[] = "bwm.detector";
constexpr size_t kMaximumCandidates = 32;

struct PixelRegion { int x; int y; int width; int height; };

float clampUnit(float value) { return std::clamp(value, 0.0F, 1.0F); }

float intersectionOverUnion(const PersonBox &a, const PersonBox &b)
{
    const float left = std::max(a.x, b.x);
    const float top = std::max(a.y, b.y);
    const float right = std::min(a.x + a.width, b.x + b.width);
    const float bottom = std::min(a.y + a.height, b.y + b.height);
    const float intersection = std::max(0.0F, right - left) * std::max(0.0F, bottom - top);
    const float union_area = a.width * a.height + b.width * b.height - intersection;
    return union_area > 0.0F ? intersection / union_area : 0.0F;
}

PixelRegion tileRegion(uint8_t column, uint8_t row, uint16_t frame_width, uint16_t frame_height)
{
    const float horizontal_divisor = kTileColumns - (kTileColumns - 1) * kTileOverlap;
    const float vertical_divisor = kTileRows - (kTileRows - 1) * kTileOverlap;
    const int tile_width = static_cast<int>(std::ceil(frame_width / horizontal_divisor));
    const int tile_height = static_cast<int>(std::ceil(frame_height / vertical_divisor));
    const int step_x = kTileColumns > 1 ? (frame_width - tile_width) / (kTileColumns - 1) : 0;
    const int step_y = kTileRows > 1 ? (frame_height - tile_height) / (kTileRows - 1) : 0;
    const int x = column == kTileColumns - 1 ? frame_width - tile_width : column * step_x;
    const int y = row == kTileRows - 1 ? frame_height - tile_height : row * step_y;
    return {x, y, tile_width, tile_height};
}

void resizeRegionRgb888(const uint8_t *source, uint16_t source_width,
                        const PixelRegion &region, uint8_t *destination)
{
    // Bilinear crop/resize directly into the model's native input dimensions.
    for (uint16_t dy = 0; dy < kModelInputHeight; ++dy) {
        const float sy = region.y + ((dy + 0.5F) * region.height / kModelInputHeight) - 0.5F;
        const float sy_floor = std::floor(sy);
        const int y0 = std::clamp(static_cast<int>(sy_floor), region.y, region.y + region.height - 1);
        const int y1 = std::min(y0 + 1, region.y + region.height - 1);
        const float fy = sy - sy_floor;
        for (uint16_t dx = 0; dx < kModelInputWidth; ++dx) {
            const float sx = region.x + ((dx + 0.5F) * region.width / kModelInputWidth) - 0.5F;
            const float sx_floor = std::floor(sx);
            const int x0 = std::clamp(static_cast<int>(sx_floor), region.x, region.x + region.width - 1);
            const int x1 = std::min(x0 + 1, region.x + region.width - 1);
            const float fx = sx - sx_floor;
            const size_t destination_offset = (static_cast<size_t>(dy) * kModelInputWidth + dx) * 3;
            for (int channel = 0; channel < 3; ++channel) {
                const float top = source[(static_cast<size_t>(y0) * source_width + x0) * 3 + channel] * (1.0F - fx) +
                                  source[(static_cast<size_t>(y0) * source_width + x1) * 3 + channel] * fx;
                const float bottom = source[(static_cast<size_t>(y1) * source_width + x0) * 3 + channel] * (1.0F - fx) +
                                     source[(static_cast<size_t>(y1) * source_width + x1) * 3 + channel] * fx;
                destination[destination_offset + channel] =
                    static_cast<uint8_t>(top * (1.0F - fy) + bottom * fy);
            }
        }
    }
}
}  // namespace

class EspDlPedestrianDetector::Impl {
public:
    uint16_t source_width = 0;
    uint16_t source_height = 0;
    uint8_t *rgb888 = nullptr;
    uint8_t *tile_rgb888 = nullptr;
    PedestrianDetect *model = nullptr;
};

EspDlPedestrianDetector::~EspDlPedestrianDetector()
{
    if (impl_ != nullptr) {
        delete impl_->model;
        heap_caps_free(impl_->tile_rgb888);
        heap_caps_free(impl_->rgb888);
        delete impl_;
    }
}

bool EspDlPedestrianDetector::initialise(uint16_t source_width, uint16_t source_height)
{
    impl_ = new (std::nothrow) Impl();
    if (impl_ == nullptr) return false;
    impl_->source_width = source_width;
    impl_->source_height = source_height;
    const size_t full_bytes = static_cast<size_t>(source_width) * source_height * 3;
    const size_t tile_bytes = static_cast<size_t>(kModelInputWidth) * kModelInputHeight * 3;
    impl_->rgb888 = static_cast<uint8_t *>(heap_caps_malloc(full_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (tiledModeEnabled()) {
        impl_->tile_rgb888 = static_cast<uint8_t *>(heap_caps_malloc(tile_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    }
    if (impl_->rgb888 == nullptr || (tiledModeEnabled() && impl_->tile_rgb888 == nullptr)) {
        ESP_LOGE(kTag, "PSRAM workspace allocation failed: full=%u tile=%u",
                 static_cast<unsigned>(full_bytes), tiledModeEnabled() ? static_cast<unsigned>(tile_bytes) : 0U);
        return false;
    }
    impl_->model = new (std::nothrow) PedestrianDetect();
    if (impl_->model == nullptr) return false;
    ESP_LOGI(kTag,
             "model=PICO_S8_V1 framework=ESP-DL input=%ux%u mode=%s source=%ux%u regions=%u overlap=%.0f%% rgb_psram=%u",
             static_cast<unsigned>(kModelInputWidth), static_cast<unsigned>(kModelInputHeight),
             inferenceModeName(), static_cast<unsigned>(source_width), static_cast<unsigned>(source_height),
             static_cast<unsigned>(tiledModeEnabled() ? kTileColumns * kTileRows : 1), kTileOverlap * 100.0F,
             static_cast<unsigned>(full_bytes + (tiledModeEnabled() ? tile_bytes : 0)));
    return true;
}

PersonDetection EspDlPedestrianDetector::detect(const camera_fb_t &jpeg_frame)
{
    PersonDetection output;
    if (impl_ == nullptr || impl_->model == nullptr || jpeg_frame.format != PIXFORMAT_JPEG) return output;
    if (jpeg_frame.width != impl_->source_width || jpeg_frame.height != impl_->source_height) {
        ESP_LOGE(kTag, "unexpected frame dimensions %ux%u", jpeg_frame.width, jpeg_frame.height);
        return output;
    }

    const int64_t decode_started = esp_timer_get_time();
    if (!fmt2rgb888(jpeg_frame.buf, jpeg_frame.len, jpeg_frame.format, impl_->rgb888)) {
        ESP_LOGE(kTag, "JPEG to RGB888 conversion failed");
        return output;
    }
    output.decode_ms = static_cast<uint32_t>((esp_timer_get_time() - decode_started) / 1000);

    std::array<PersonBox, kMaximumCandidates> candidates = {};
    size_t candidate_count = 0;
    const uint8_t columns = tiledModeEnabled() ? kTileColumns : 1;
    const uint8_t rows = tiledModeEnabled() ? kTileRows : 1;
    output.regions_scanned = columns * rows;

    for (uint8_t row = 0; row < rows; ++row) {
        for (uint8_t column = 0; column < columns; ++column) {
            PixelRegion region{0, 0, static_cast<int>(jpeg_frame.width), static_cast<int>(jpeg_frame.height)};
            uint8_t *input_data = impl_->rgb888;
            uint16_t input_width = jpeg_frame.width;
            uint16_t input_height = jpeg_frame.height;
            if (tiledModeEnabled()) {
                region = tileRegion(column, row, jpeg_frame.width, jpeg_frame.height);
                const int64_t resize_started = esp_timer_get_time();
                resizeRegionRgb888(impl_->rgb888, jpeg_frame.width, region, impl_->tile_rgb888);
                output.resize_ms += static_cast<uint32_t>((esp_timer_get_time() - resize_started) / 1000);
                input_data = impl_->tile_rgb888;
                input_width = kModelInputWidth;
                input_height = kModelInputHeight;
            }

            dl::image::img_t image = {};
            image.data = input_data;
            image.width = input_width;
            image.height = input_height;
            image.pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB888;
            const int64_t inference_started = esp_timer_get_time();
            const auto &results = impl_->model->run(image);
            output.inference_ms += static_cast<uint32_t>((esp_timer_get_time() - inference_started) / 1000);

            for (const auto &result : results) {
                if (result.box.size() < 4 || candidate_count == candidates.size()) continue;
                const float x1 = clampUnit(static_cast<float>(result.box[0]) / input_width);
                const float y1 = clampUnit(static_cast<float>(result.box[1]) / input_height);
                const float x2 = clampUnit(static_cast<float>(result.box[2]) / input_width);
                const float y2 = clampUnit(static_cast<float>(result.box[3]) / input_height);
                PersonBox &candidate = candidates[candidate_count++];
                candidate.confidence = result.score;
                candidate.x = clampUnit((region.x + x1 * region.width) / jpeg_frame.width);
                candidate.y = clampUnit((region.y + y1 * region.height) / jpeg_frame.height);
                const float right = clampUnit((region.x + x2 * region.width) / jpeg_frame.width);
                const float bottom = clampUnit((region.y + y2 * region.height) / jpeg_frame.height);
                candidate.width = std::max(0.0F, right - candidate.x);
                candidate.height = std::max(0.0F, bottom - candidate.y);
            }
        }
    }

    std::sort(candidates.begin(), candidates.begin() + candidate_count,
              [](const PersonBox &a, const PersonBox &b) { return a.confidence > b.confidence; });
    for (size_t index = 0; index < candidate_count && output.box_count < output.boxes.size(); ++index) {
        bool duplicate = false;
        for (size_t kept = 0; kept < output.box_count; ++kept) {
            if (intersectionOverUnion(candidates[index], output.boxes[kept]) >= kCrossTileNmsIou) {
                duplicate = true;
                break;
            }
        }
        if (!duplicate) output.boxes[output.box_count++] = candidates[index];
    }

    output.person = output.box_count > 0;
    if (output.person) {
        const PersonBox &best = output.boxes[0];
        output.confidence = best.confidence;
        output.x = best.x;
        output.y = best.y;
        output.width = best.width;
        output.height = best.height;
    }
    return output;
}
