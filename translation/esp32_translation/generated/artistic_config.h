#pragma once
// Generated from runtime.yaml and voice_reactions.yaml; do not hand-edit.
#include <cmath>
#include <cstdint>
namespace bwm {
constexpr bool kInitiallyActive = true;
constexpr uint32_t kSessionTimeoutMs = 600000u;
constexpr uint32_t kSegmentDurationMs = 600000u;
constexpr uint32_t kSolenoidAdmissionDelayMs = 4000u;
constexpr uint16_t kReactionPulseMs = 150u;
enum class Reaction : uint8_t { kSimultaneousThenSequence, kCascade, kTripleTap, kSplitGroups, kDoubleTap };
constexpr float kSileroUpper[5] = {0.002f, 0.006f, 0.02f, 0.06f, INFINITY};
constexpr Reaction kBandReaction[5] = {static_cast<Reaction>(0), static_cast<Reaction>(1), static_cast<Reaction>(3), static_cast<Reaction>(4), static_cast<Reaction>(0)};
constexpr uint8_t kDefaultWeights[5] = {1, 1, 1, 0, 1};
constexpr uint32_t kQuietGapMs = 500u;
constexpr uint32_t kSimultaneousWaitMs = 500u;
constexpr uint32_t kSimultaneousSpacingMs = 200u;
constexpr uint32_t kSimultaneousTailMs = 1000u;
constexpr uint32_t kCascadeSpacingMs = 300u;
constexpr uint32_t kCascadeTailMs = 1000u;
constexpr uint32_t kSplitWaitMs = 2000u;
constexpr uint32_t kSplitTailMs = 2000u;
constexpr uint32_t kTripleWindowMs = 3000u;
constexpr uint8_t kTripleCount = 3u;
constexpr uint32_t kTripleSpacingMs = 200u;
constexpr uint32_t kDoubleWindowMs = 3000u;
constexpr uint8_t kDoubleCount = 2u;
constexpr uint32_t kDoubleSpacingMs = 400u;
}  // namespace bwm
