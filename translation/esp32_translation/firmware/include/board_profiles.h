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

#if defined(BWM_BOARD_XIAO_ESP32S3)
// Preserve the live-tested Tuesday fallback output map. D2/GPIO3 is skipped
// because it is a strapping pin. D6/D7 become UART and D9 is the local button.
constexpr BoardProfile kBoard{"xiao_esp32s3_sense", {1, 2, 4, 5, 6, 7}, 8, 43, 44};
#elif defined(BWM_BOARD_ESP32S3_DEVKITC)
// Generic DevKitC/WROOM profile. Avoid USB GPIO19/20 and strapping pins.
constexpr BoardProfile kBoard{"esp32s3_devkitc", {4, 5, 6, 7, 15, 16}, 17, 18, 8};
#else
// Native tests do not touch GPIO, but retain deterministic topology metadata.
constexpr BoardProfile kBoard{"native_test", {1, 2, 4, 5, 6, 7}, 8, 43, 44};
#endif

}  // namespace bwm
