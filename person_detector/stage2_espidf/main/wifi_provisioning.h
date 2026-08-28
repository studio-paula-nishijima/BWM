#pragma once

#include <cstddef>
#include <cstdint>

struct WifiNetworkInfo {
    char ssid[33] = {};
    int8_t rssi = 0;
    bool secure = false;
};

// Owns Wi-Fi station recovery and the temporary setup access point. Saved
// credentials are isolated from the trigger-zone namespace in NVS.
class WifiProvisioningManager {
public:
    class Impl;

    ~WifiProvisioningManager();

    bool begin();
    bool connected() const;
    bool provisioning() const;
    bool recovering() const;
    bool hasSavedCredentials() const;
    const char *setupApSsid() const;
    const char *operatingModeName() const;
    uint32_t recoveryRetrySeconds() const;

    size_t scan(WifiNetworkInfo *networks, size_t capacity);
    bool provision(const char *ssid, const char *password, char *message, size_t message_size);
    bool forgetAndRestart(char *message, size_t message_size);

private:
    Impl *impl_ = nullptr;
};
