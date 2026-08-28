#pragma once

#include "esp_camera.h"
#include "motion_detector.h"
#include "activation_transport.h"
#include "person_detector.h"
#include "trigger_zone_config.h"
#include "wifi_provisioning.h"

// A deliberately low-rate browser preview. Frames are copied from the
// detector's capture path, so HTTP requests never compete for the camera.
class PreviewServer {
public:
    class Impl;

    bool begin(TriggerZoneConfig &trigger_zone, ActivationTransport &activation_transport,
               WifiProvisioningManager &wifi);
    void publishFrame(const camera_fb_t &frame);
    void publishPersonDetection(const PersonDetection &detection);
    void publishMotionDetection(const MotionDetection &detection);

private:
    Impl *impl_ = nullptr;
};
