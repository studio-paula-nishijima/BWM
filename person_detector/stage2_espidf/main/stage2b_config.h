#pragma once

#include <cstddef>
#include <cstdint>

enum class DetectionMode : uint8_t { Person = 0, Motion = 1 };

// Compile-time selection keeps the inactive detector's large runtime buffers
// unallocated. Change this to Person for a direct Stage 2A comparison.
constexpr DetectionMode kDetectionMode = DetectionMode::Motion;

struct NormalisedZone {
    float x;
    float y;
    float width;
    float height;
};

// The centred 60% of the full camera frame is the safe fallback.
constexpr NormalisedZone kDefaultMotionTriggerZone{0.20F, 0.20F, 0.60F, 0.60F};
constexpr float kMinimumTriggerZoneSize = 0.05F;

constexpr uint16_t kMotionFrameWidth = 640;
constexpr uint16_t kMotionFrameHeight = 480;
constexpr uint16_t kMotionGridWidth = 80;
constexpr uint16_t kMotionGridHeight = 60;
constexpr uint8_t kMotionPixelDifferenceThreshold = 20;
constexpr uint8_t kMotionNeighbourThreshold = 3;
constexpr size_t kMotionMinimumBlobPixels = 12;
// A likely physical blob changes local edge structure. A brightness-only blob
// below this mean gradient-difference level is treated as a likely shadow.
constexpr float kMotionMinimumStructureChange = 6.0F;
constexpr float kMotionShadowMinimumLuminanceChange = 20.0F;
// Strong, localised, structurally plausible in-zone motion can confirm at once.
constexpr float kStrongMotionMinimumChangedFraction = 0.012F;
constexpr float kStrongMotionMinimumLuminanceChange = 28.0F;
constexpr float kStrongMotionMinimumStructureChange = 9.0F;
constexpr float kStrongMotionMaximumBoxFraction = 0.45F;
constexpr float kMotionGlobalChangedFraction = 0.55F;
constexpr float kMotionLargeLuminanceShift = 30.0F;
constexpr float kMotionLuminanceChangedFraction = 0.35F;
constexpr size_t kMotionConfirmationHits = 2;
constexpr size_t kMotionConfirmationWindow = 4;
constexpr size_t kMotionMaximumBoxes = 8;
constexpr uint32_t kMotionMemoryLogEveryScans = 20;

static_assert(kMotionConfirmationHits > 0);
static_assert(kMotionConfirmationHits <= kMotionConfirmationWindow);
static_assert(kMotionConfirmationWindow <= 16);
static_assert(kDefaultMotionTriggerZone.x >= 0.0F && kDefaultMotionTriggerZone.y >= 0.0F);
static_assert(kDefaultMotionTriggerZone.x + kDefaultMotionTriggerZone.width <= 1.0F);
static_assert(kDefaultMotionTriggerZone.y + kDefaultMotionTriggerZone.height <= 1.0F);

constexpr bool motionModeEnabled() { return kDetectionMode == DetectionMode::Motion; }
constexpr const char *detectionModeName() { return motionModeEnabled() ? "motion" : "person"; }
