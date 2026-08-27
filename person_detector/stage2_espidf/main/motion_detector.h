#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "esp_camera.h"
#include "stage2b_config.h"

enum class MotionConfirmationReason : uint8_t {
    None = 0,
    StrongImmediate,
    NOfM,
    AwaitingNOfM,
    RejectedShadow,
    RejectedGlobalIllumination,
    RejectedNoise,
};

const char *motionConfirmationReasonName(MotionConfirmationReason reason);

struct MotionBox {
    float x = 0.0F;
    float y = 0.0F;
    float width = 0.0F;
    float height = 0.0F;
    float centre_x = 0.0F;
    float centre_y = 0.0F;
    float area_fraction = 0.0F;
    float mean_luminance_change = 0.0F;
    float mean_structure_change = 0.0F;
    bool inside_trigger_zone = false;
    bool strong_motion = false;
    bool likely_shadow = false;
};

struct MotionDetection {
    bool reference_ready = false;
    bool motion = false;
    bool in_zone_hit = false;
    bool illumination_change = false;
    bool confirmed = false;
    bool strong_in_zone_motion = false;
    std::array<MotionBox, kMotionMaximumBoxes> boxes = {};
    size_t box_count = 0;
    std::array<MotionBox, kMotionMaximumBoxes> rejected_boxes = {};
    size_t rejected_box_count = 0;
    size_t recent_hits = 0;
    size_t recent_count = 0;
    float changed_fraction = 0.0F;
    float global_luminance_shift = 0.0F;
    float largest_blob_area = 0.0F;
    MotionConfirmationReason confirmation_reason = MotionConfirmationReason::None;
    uint32_t decode_ms = 0;
    uint32_t processing_ms = 0;
};

class MotionDetector {
public:
    ~MotionDetector();
    bool initialise(uint16_t source_width, uint16_t source_height);
    MotionDetection detect(const camera_fb_t &jpeg_frame, const NormalisedZone &trigger_zone);
    size_t workspaceBytes() const;

private:
    class Impl;
    Impl *impl_ = nullptr;
};
