#pragma once

#include <atomic>

#include "activation_event.h"

// ESP BLE peripheral for the documented BWM Vision activation GATT service.
// Notifications are deliberately best-effort: no connected Pi means an event
// is dropped, while the detector continues independently.
class BleActivationPublisher {
public:
    bool begin();
    bool publish(const ActivationEvent &event);
    bool advertising() const { return advertising_.load(); }
    bool connected() const { return connected_.load(); }
    const char *lastEventId() const { return last_event_id_; }
    const char *lastResult() const { return last_result_; }
    void onConnectionChanged(bool connected, bool advertising);

private:
    std::atomic_bool advertising_{false};
    std::atomic_bool connected_{false};
    char last_event_id_[37] = {};
    char last_result_[32] = "not_sent";
};
