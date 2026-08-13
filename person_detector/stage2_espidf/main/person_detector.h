#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "esp_camera.h"

struct PersonBox {
    float confidence = 0.0F;
    float x = 0.0F;
    float y = 0.0F;
    float width = 0.0F;
    float height = 0.0F;
};

// Coordinates are normalised to the full source frame, even in tiled mode.
struct PersonDetection {
    static constexpr size_t kMaximumBoxes = 8;

    bool person = false;
    // Primary/highest-confidence box retained for downstream compatibility.
    float confidence = 0.0F;
    float x = 0.0F;
    float y = 0.0F;
    float width = 0.0F;
    float height = 0.0F;
    std::array<PersonBox, kMaximumBoxes> boxes = {};
    size_t box_count = 0;
    uint8_t regions_scanned = 0;
    uint32_t decode_ms = 0;
    uint32_t resize_ms = 0;
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
