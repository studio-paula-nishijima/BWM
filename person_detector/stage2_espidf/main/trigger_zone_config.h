#pragma once

#include "stage2b_config.h"

class TriggerZoneConfig {
public:
    TriggerZoneConfig() = default;
    ~TriggerZoneConfig();

    // Runtime operation remains available with defaults even if NVS fails.
    bool begin();
    NormalisedZone current() const;
    NormalisedZone defaultZone() const { return kDefaultMotionTriggerZone; }
    bool apply(const NormalisedZone &zone);
    bool save();
    void resetToDefault();

    static bool valid(const NormalisedZone &zone);

private:
    class Impl;
    Impl *impl_ = nullptr;
};
