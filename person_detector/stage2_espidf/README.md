# BWM vision node — Stage 2 (ESP-IDF / ESP-DL)

This is a separate Stage 2 project. It does not replace the verified Arduino /
PlatformIO Stage 1 camera and browser-preview baseline in the parent folder.

It captures a QVGA JPEG frame from the XIAO ESP32S3 Sense, converts it locally
to RGB888, runs Espressif's `PedestrianDetect` model, and prints the highest
confidence person's normalised bounding box every 500 ms.

```text
person=true confidence=0.880 x=0.420 y=0.310 w=0.180 h=0.510 inference_ms=130
```

No image or inference result leaves the board. Wi-Fi, MQTT, persistence, the
zone evaluator, and browser overlays deliberately remain out of this stage.

## Build requirements

- ESP-IDF **v5.5.x** installed through Espressif's VS Code extension.
- XIAO ESP32S3 Sense connected on its normal USB serial port.
- Internet access only for the first build, when ESP-IDF Component Manager
  downloads the pinned camera and ESP-DL model components. The flashed model
  runs locally afterwards.

## Build and flash

Open this `stage2_espidf` folder in a VS Code terminal where the ESP-IDF v5.5
environment is active, then run:

```powershell
idf.py set-target esp32s3
idf.py build
idf.py -p COM3 flash monitor
```

## Browser preview

Stage 2 reuses the ignored `../wifi_credentials.h` file created for Stage 1.
When it connects, the monitor prints `bwm.preview: preview ready: open
http://.../`. Open that address on the same Wi-Fi network. The page refreshes
a copied camera JPEG at about 1.4 frames per second and overlays the latest
detector box. This is intentionally a low-rate diagnostic view: browser
requests do not acquire camera frames, so they do not interfere with inference.

Use your actual serial port if it is not `COM3`. `idf.py build` will create
`managed_components/` and `dependencies.lock`; both record the resolved model
dependencies and should be retained after the first successful build.

## Acceptance check

- Startup reports QVGA camera and ESP-DL model readiness.
- With no person in frame, serial output regularly reports `person=false`.
- With one person clearly in frame, it reports `person=true` with a confidence,
  `x`, `y`, `w`, and `h` between 0 and 1.
- Move within the frame: bounding-box coordinates should follow the movement.
- Confirm the system detects within the required one-to-two-second window.

The generic pedestrian model is a starting point. Test seated, partially framed,
and backlit visitors before relying on it in an exhibit; a venue-trained model
can later replace this class without changing its caller.
