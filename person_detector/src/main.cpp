#include "stage1_app.h"

// PlatformIO receives BWM_PLATFORMIO_BUILD from platformio.ini. Arduino IDE
// uses person_detector.ino instead, while still compiling this file from src/.
#if defined(BWM_PLATFORMIO_BUILD)
void setup() { stage1Setup(); }
void loop() { stage1Loop(); }
#endif
