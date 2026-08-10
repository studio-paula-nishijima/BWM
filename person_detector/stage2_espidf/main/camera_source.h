#pragma once

#include "esp_camera.h"

class CameraSource {
public:
    bool initialise();
    camera_fb_t *capture();
    void release(camera_fb_t *frame);
};
