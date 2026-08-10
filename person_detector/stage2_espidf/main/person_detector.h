#pragma once

#include <cstdint>

#include "esp_camera.h"

// All coordinates are normalised to the source camera frame (0.0–1.0).
struct PersonDetection {
    bool person = false;
    float confidence = 0.0F;
    float x = 0.0F;
    float y = 0.0F;
    float width = 0.0F;
    float height = 0.0F;
    uint32_t inference_ms = 0;
};

class PersonDetector {
public:
    virtual ~PersonDetector() = default;
    virtual bool initialise(uint16_t source_width, uint16_t source_height) = 0;
    virtual PersonDetection detect(const camera_fb_t &jpeg_frame) = 0;
};

class EspDlPedestrianDetector final : public PersonDetector {
public:
    ~EspDlPedestrianDetector() override;
    bool initialise(uint16_t source_width, uint16_t source_height) override;
    PersonDetection detect(const camera_fb_t &jpeg_frame) override;

private:
    class Impl;
    Impl *impl_ = nullptr;
};
