#include "camera_source.h"

#include "esp_log.h"
#include "esp_psram.h"

namespace {
constexpr char kTag[] = "bwm.camera";

// Seeed Studio XIAO ESP32S3 Sense camera expansion-board wiring.
constexpr int kPinPwdn = -1;
constexpr int kPinReset = -1;
constexpr int kPinXclk = 10;
constexpr int kPinSiod = 40;
constexpr int kPinSioc = 39;
constexpr int kPinD7 = 48;
constexpr int kPinD6 = 11;
constexpr int kPinD5 = 12;
constexpr int kPinD4 = 14;
constexpr int kPinD3 = 16;
constexpr int kPinD2 = 18;
constexpr int kPinD1 = 17;
constexpr int kPinD0 = 15;
constexpr int kPinVsync = 38;
constexpr int kPinHref = 47;
constexpr int kPinPclk = 13;
}  // namespace

bool CameraSource::initialise()
{
    if (!esp_psram_is_initialized()) {
        ESP_LOGE(kTag, "PSRAM is unavailable; check XIAO ESP32S3 Sense settings");
        return false;
    }

    camera_config_t config = {};
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = kPinD0;
    config.pin_d1 = kPinD1;
    config.pin_d2 = kPinD2;
    config.pin_d3 = kPinD3;
    config.pin_d4 = kPinD4;
    config.pin_d5 = kPinD5;
    config.pin_d6 = kPinD6;
    config.pin_d7 = kPinD7;
    config.pin_xclk = kPinXclk;
    config.pin_pclk = kPinPclk;
    config.pin_vsync = kPinVsync;
    config.pin_href = kPinHref;
    config.pin_sccb_sda = kPinSiod;
    config.pin_sccb_scl = kPinSioc;
    config.pin_pwdn = kPinPwdn;
    config.pin_reset = kPinReset;
    config.xclk_freq_hz = 20000000;

    // JPEG capture avoids sustained raw-RGB writes to PSRAM. The detector
    // converts each QVGA JPEG to RGB888 only when it is about to infer.
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 12;
    // Match the proven Stage 1 capture pipeline. Two PSRAM buffers let the
    // driver acquire the next JPEG while the previous one is decoded.
    config.fb_count = 2;
    config.grab_mode = CAMERA_GRAB_LATEST;
    config.fb_location = CAMERA_FB_IN_PSRAM;

    const esp_err_t result = esp_camera_init(&config);
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "camera initialisation failed: %s", esp_err_to_name(result));
        return false;
    }
    ESP_LOGI(kTag, "camera ready: QVGA JPEG, two PSRAM frame buffers");
    return true;
}

camera_fb_t *CameraSource::capture()
{
    return esp_camera_fb_get();
}

void CameraSource::release(camera_fb_t *frame)
{
    if (frame != nullptr) {
        esp_camera_fb_return(frame);
    }
}
