# BWM vision node — Stage 1

This is a standalone firmware baseline for the Seeed Studio XIAO ESP32S3 Sense.
It deliberately implements **only Stage 1**: serial diagnostics, PSRAM and
camera initialisation, repeatable JPEG captures, temporary development Wi-Fi,
and a browser camera preview.

## Foundation chosen

The project uses the Arduino framework through PlatformIO. This is the best
starting point here because the ESP32 Arduino core bundles Espressif's supported
`esp32-camera` driver, Seeed publishes a XIAO Sense Arduino camera baseline,
and the workflow is close to the existing Arduino desktop experience. PlatformIO
makes the board, PSRAM, compiler and serial-monitor settings versionable.

ESP-IDF remains a viable later migration if the selected detection model needs
an ESP-IDF-only integration. The camera acquisition API used here is the same
Espressif `esp_camera` API, so Stage 1 hardware work is not discarded.

## Important board decisions

- The XIAO ESP32S3 Sense camera configuration requires its 8 MB octal PSRAM.
  The firmware refuses to run the camera if PSRAM is absent rather than silently
  using unreliable small DRAM buffers.
- Stage 1 captures JPEG at VGA (640×480) with two PSRAM frame buffers and
  `CAMERA_GRAB_LATEST`. This provides a responsive browser preview and a stable
  baseline. It is intentionally not the inference format.
- Later local detection should acquire or resize a smaller RGB frame (typically
  96–320 pixels square, model dependent) while JPEG capture continues for the
  diagnostic UI. ESP32-S3 does colour conversion in software, so full-resolution
  RGB inference is not appropriate.
- The OV2640/OV5640 camera sensor supplied with Sense variants can differ. The
  pin map is shared; this Stage 1 configuration uses JPEG, which both support.
- ESP32-S3 has vector instructions but no large vision accelerator. A future
  person detector must be a small, quantised model with bounded RAM, and should
  be evaluated against real venue lighting before committing to it. No AI model
  is included in this stage.

## Build and flash

1. Install [PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/index.html), then copy `wifi_credentials.h.example` to `wifi_credentials.h`.
2. Put temporary development Wi-Fi credentials in that copied file. It is Git-ignored.
3. Connect the XIAO by USB-C and run:

   ```powershell
   cd C:\Users\mail\Documents\ChatGPT\New project\BWM-review\person_detector
   pio run --target upload
   pio device monitor
   ```

4. At 115200 baud, confirm `Camera ready` followed by `WiFi connected`. Open
   the IP address printed in the serial monitor. `/capture` serves one JPEG and
   `/` serves an auto-refreshing four-FPS diagnostic preview.

If the board does not appear during upload, enter its bootloader: hold **BOOT**,
press and release **RESET**, then release **BOOT**.

## Stage 1 acceptance checklist

- Successful PlatformIO compile for `xiao_esp32s3_sense`.
- Serial output reports detected PSRAM and a successful initial JPEG capture.
- A periodic `Camera capture OK` line confirms repeated captures.
- With temporary credentials configured, the serial output reports a LAN IP and
  the browser preview/capture endpoints work on the local network.

## Arduino IDE

Open `person_detector.ino` from this folder. Arduino IDE uses that root sketch
as its entry point and compiles the reusable implementation in `src/`. Copy
`wifi_credentials.h.example` to `wifi_credentials.h` first. Select the
**XIAO_ESP32S3** board, set PSRAM to **OPI PSRAM**, and set USB CDC On Boot to
**Enabled** before uploading.

## Sources

- [Seeed camera usage for XIAO ESP32S3 Sense](https://wiki.seeedstudio.com/xiao_esp32s3_camera_usage/)
- [Espressif esp32-camera driver](https://github.com/espressif/esp32-camera)
- [Espressif Arduino CameraWebServer example](https://github.com/espressif/arduino-esp32/tree/master/libraries/ESP32/examples/Camera/CameraWebServer)
