#pragma once

#include <cstdint>

namespace bwm {

struct BoardProfile {
  const char* name;
  uint8_t outputs[6];
  uint8_t button;
  uint8_t uart_tx;
  uint8_t uart_rx;
};

#if defined(BWM_BOARD_ESP32S3_DEVKITC_N16R8)
// ESP32-S3-DevKitC-1 / WROOM-1-N16R8. These header pins avoid strapping
// GPIO0/3/45/46, native USB GPIO19/20, UART0 GPIO43/44, JTAG GPIO39-42,
// RGB LED GPIO38/48, and the flash/Octal-PSRAM buses GPIO26-37.
constexpr BoardProfile kBoard{"esp32s3_devkitc_1_wroom_1_n16r8",
                              {4, 5, 6, 7, 15, 16}, 17, 18, 8};
#else
// Native tests do not touch GPIO, but retain deterministic topology metadata.
constexpr BoardProfile kBoard{"native_test", {4, 5, 6, 7, 15, 16}, 17, 18, 8};
#endif

}  // namespace bwm
