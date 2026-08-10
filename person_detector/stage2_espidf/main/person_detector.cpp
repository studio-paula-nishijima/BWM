#include "person_detector.h"

#include <algorithm>
#include <new>

#include "dl_image_define.hpp"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "img_converters.h"
#include "pedestrian_detect.hpp"

namespace {
constexpr char kTag[] = "bwm.detector";

float normalise(int value, uint16_t extent)
{
    if (extent == 0) return 0.0F;
    return std::clamp(static_cast<float>(value) / static_cast<float>(extent), 0.0F, 1.0F);
}
}  // namespace

class EspDlPedestrianDetector::Impl {
public:
    uint16_t source_width = 0;
    uint16_t source_height = 0;
    uint8_t *rgb888 = nullptr;
    PedestrianDetect *model = nullptr;
};

EspDlPedestrianDetector::~EspDlPedestrianDetector()
{
    if (impl_ != nullptr) {
        delete impl_->model;
        heap_caps_free(impl_->rgb888);
        delete impl_;
    }
}

bool EspDlPedestrianDetector::initialise(uint16_t source_width, uint16_t source_height)
{
    impl_ = new (std::nothrow) Impl();
    if (impl_ == nullptr) {
        ESP_LOGE(kTag, "could not allocate detector state");
        return false;
    }
    impl_->source_width = source_width;
    impl_->source_height = source_height;
    const size_t image_bytes = static_cast<size_t>(source_width) * source_height * 3;
    impl_->rgb888 = static_cast<uint8_t *>(heap_caps_malloc(image_bytes, MALLOC_CAP_SPIRAM));
    if (impl_->rgb888 == nullptr) {
        ESP_LOGE(kTag, "could not allocate %u-byte RGB working image in PSRAM", image_bytes);
        return false;
    }

    // Construct only after the camera and image workspace are stable to limit
    // heap fragmentation before ESP-DL allocates its model workspace.
    impl_->model = new (std::nothrow) PedestrianDetect();
    if (impl_->model == nullptr) {
        ESP_LOGE(kTag, "could not create PedestrianDetect model");
        return false;
    }
    ESP_LOGI(kTag, "ESP-DL pedestrian model ready (%ux%u source)", source_width, source_height);
    return true;
}

PersonDetection EspDlPedestrianDetector::detect(const camera_fb_t &jpeg_frame)
{
    PersonDetection output;
    if (impl_ == nullptr || impl_->model == nullptr || jpeg_frame.format != PIXFORMAT_JPEG) {
        ESP_LOGE(kTag, "detector is not ready or received a non-JPEG frame");
        return output;
    }
    if (!fmt2rgb888(jpeg_frame.buf, jpeg_frame.len, jpeg_frame.format, impl_->rgb888)) {
        ESP_LOGE(kTag, "JPEG to RGB888 conversion failed");
        return output;
    }

    dl::image::img_t image = {};
    image.data = impl_->rgb888;
    image.width = jpeg_frame.width;
    image.height = jpeg_frame.height;
    image.pix_type = dl::image::DL_IMAGE_PIX_TYPE_RGB888;

    const int64_t started_us = esp_timer_get_time();
    const auto &results = impl_->model->run(image);
    output.inference_ms = static_cast<uint32_t>((esp_timer_get_time() - started_us) / 1000);
    if (results.empty()) return output;

    const auto best = std::max_element(results.begin(), results.end(), [](const auto &left, const auto &right) {
        return left.score < right.score;
    });
    if (best == results.end() || best->box.size() < 4) return output;

    const int x1 = best->box[0];
    const int y1 = best->box[1];
    const int x2 = best->box[2];
    const int y2 = best->box[3];
    output.person = true;
    output.confidence = best->score;
    output.x = normalise(x1, jpeg_frame.width);
    output.y = normalise(y1, jpeg_frame.height);
    output.width = normalise(x2 - x1, jpeg_frame.width);
    output.height = normalise(y2 - y1, jpeg_frame.height);
    return output;
}
