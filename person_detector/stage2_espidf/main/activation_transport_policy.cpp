#include "activation_transport_policy.h"

const char *ActivationTransportPolicy::currentName() const
{
    return current_ == AutomaticTransport::Ble ? "ble" : "mqtt";
}

namespace {
constexpr bool verifiesFallbackAndReclaimHysteresis()
{
    ActivationTransportPolicy policy;
    policy.reset(100);
    policy.update(100, true);
    if (policy.current() != AutomaticTransport::Mqtt) return false;

    policy.update(200, false);
    policy.update(3199, false);
    if (policy.current() != AutomaticTransport::Mqtt || policy.fallbackRemainingMs(3199) != 1) return false;
    policy.update(3200, false);
    if (policy.current() != AutomaticTransport::Ble) return false;

    policy.update(4000, true);
    policy.update(13999, true);
    if (policy.current() != AutomaticTransport::Ble || policy.reclaimRemainingMs(13999) != 1) return false;
    policy.update(14000, true);
    return policy.current() == AutomaticTransport::Mqtt;
}

constexpr bool verifiesContinuousHealthRequirement()
{
    ActivationTransportPolicy policy;
    policy.reset(0);
    policy.update(3000, false);
    if (policy.current() != AutomaticTransport::Ble) return false;
    policy.update(4000, true);
    policy.update(9000, false);
    policy.update(10000, true);
    policy.update(19999, true);
    return policy.current() == AutomaticTransport::Ble;
}

static_assert(verifiesFallbackAndReclaimHysteresis(), "automatic transport thresholds regressed");
static_assert(verifiesContinuousHealthRequirement(), "MQTT reclaim must require continuous health");
}  // namespace
