#pragma once

#include <cstddef>
#include <cstdint>

enum class InferenceMode : uint8_t { FullFrame = 0, Tiled = 1 };

// Change this one setting to compare the original baseline and tiled mode.
constexpr InferenceMode kInferenceMode = InferenceMode::Tiled;

constexpr uint16_t kFullFrameWidth = 320;
constexpr uint16_t kFullFrameHeight = 240;
constexpr uint16_t kTiledFrameWidth = 640;
constexpr uint16_t kTiledFrameHeight = 480;
constexpr uint16_t kModelInputWidth = 224;
constexpr uint16_t kModelInputHeight = 224;
constexpr uint8_t kTileColumns = 2;
constexpr uint8_t kTileRows = 2;
constexpr float kTileOverlap = 0.20F;
constexpr float kCrossTileNmsIou = 0.45F;
constexpr size_t kRecentScanWindow = 5;
constexpr uint32_t kMinimumSceneIntervalMs = 500;

constexpr bool tiledModeEnabled() { return kInferenceMode == InferenceMode::Tiled; }
constexpr const char *inferenceModeName() { return tiledModeEnabled() ? "tiled" : "full_frame"; }
constexpr uint16_t sourceFrameWidth() { return tiledModeEnabled() ? kTiledFrameWidth : kFullFrameWidth; }
constexpr uint16_t sourceFrameHeight() { return tiledModeEnabled() ? kTiledFrameHeight : kFullFrameHeight; }
