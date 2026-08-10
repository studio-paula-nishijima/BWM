#pragma once

#include "esp_camera.h"
#include "person_detector.h"

// A deliberately low-rate browser preview. Frames are copied from the
// detector's capture path, so HTTP requests never compete for the camera.
class PreviewServer {
public:
    class Impl;

    bool begin();
    void publishFrame(const camera_fb_t &frame);
    void publishDetection(const PersonDetection &detection);

private:
    Impl *impl_ = nullptr;
};
