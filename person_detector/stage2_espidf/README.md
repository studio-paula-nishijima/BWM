# BWM vision node — Stage 2 (ESP-IDF / ESP-DL)

This is a separate Stage 2 project. It does not replace the verified Arduino /
PlatformIO Stage 1 camera and browser-preview baseline in the parent folder.

It captures a QVGA JPEG frame from the XIAO ESP32S3 Sense, converts it locally
to RGB888, runs Espressif's `PedestrianDetect` model, and prints the highest
confidence person's normalised bounding box every 500 ms.

```text
person=true confidence=0.880 x=0.420 y=0.310 w=0.180 h=0.510 inference_ms=130
```

No image or inference result leaves the board. Stage 6 adds an optional,
disabled-by-default MQTT *semantic state adapter*: it publishes only an
explicit installation `active`/`inactive` transition derived from the existing
`detection.person` result. It does not alter model, confidence, geometry,
counting, or camera processing.

Copy `mqtt_config.h.example` to `mqtt_config.h` and configure a local broker
URI to enable it. The messages use the common envelope and
`bwm/installation/activation` topic documented in `../../shared/messaging`;
they are QoS 1 and non-retained. Leaving the URI empty makes MQTT a no-op and
the detector continues exactly as before.

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

Wi-Fi is configured at runtime through the Stage 5 setup page; the ESP-IDF
firmware no longer reads `../wifi_credentials.h`. When it connects, the monitor
prints `bwm.preview: preview ready: open http://.../`. Open that address on the
same Wi-Fi network. The page refreshes a copied camera JPEG at about 1.4 frames
per second and overlays the latest detector box. This is intentionally a
low-rate diagnostic view: browser requests do not acquire camera frames, so
they do not interfere with inference.

## Stage 2A wide-scene experiment

The inference mode is selected in `main/stage2a_config.h`:

```cpp
constexpr InferenceMode kInferenceMode = InferenceMode::Tiled;
```

- `FullFrame` preserves the baseline: QVGA JPEG (320x240), decoded to RGB888,
  with the complete frame passed to ESP-DL. ESP-DL resizes it to the PICO S8
  v1 model's 224x224 input.
- `Tiled` captures VGA JPEG (640x480), decodes it once, and uses four 2x2
  overlapping crops. Each crop is bilinearly resized to 224x224 before the
  same model runs. The default overlap is 20 percent.

Tile results are mapped to normalised full-frame coordinates and duplicate
boxes are removed with cross-tile IoU NMS. Tile count, overlap, NMS threshold,
and the five-scan temporal diagnostics window are configurable in the same
header.

Each scene scan logs mode, detections, rolling hit ratio, JPEG decode time,
tile-resize time, aggregate and per-region inference time, total scene time,
scan period, and effective scene scans/second. Each positive box logs
confidence, normalised `x/y/w/h`, relative area, and inference time. This is
diagnostic only; it does not implement the later exhibit activation timer.

The tiled RGB workspaces consume about 1,072,128 bytes of PSRAM (a 640x480x3
decoded frame plus one 224x224x3 reusable tile), in addition to camera buffers,
the preview copy, and ESP-DL's own allocations. Boot logs report actual free
PSRAM before and after these allocations.

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

## Stage 2B motion-feasibility mode

`main/stage2b_config.h` selects one detector at build time. The checked-in
default is motion detection:

```cpp
constexpr DetectionMode kDetectionMode = DetectionMode::Motion;
```

Change `Motion` to `Person`, rebuild, and flash to repeat the existing Stage 2A
person-detector test. Only the selected detector is instantiated, avoiding two
large simultaneous PSRAM workspaces.

Motion mode keeps the VGA JPEG camera and browser preview. Each frame is
decoded once, averaged into an 80x60 grayscale grid, and compared with the
previous grid. A 3x3 neighbourhood filter removes isolated changed cells and
8-connected components produce motion boxes in normalised full-frame
coordinates. Static objects naturally disappear after the reference frame
updates.

The orange browser overlay is the runtime rectangular trigger zone in
normalized full-frame `x/y/w/h` coordinates. Cyan rectangles are accepted
motion blobs and red dots are their centres. A scan is an in-zone hit when at
least one blob centre is inside the rectangle. The initial confirmation rule
is two positive scans in the last four; it is deliberately non-consecutive and
configured by `kMotionConfirmationHits` and `kMotionConfirmationWindow`.

Frames with at least 55 percent changed pixels are flagged as global
illumination changes and rejected. The detector also rejects a lower 35 percent
changed fraction when accompanied by a mean luminance shift of at least 30
levels. These starting thresholds, the per-cell difference threshold, minimum
blob size, grid dimensions, and zone are all in `main/stage2b_config.h`.

Serial output includes changed-pixel percentage, luminance shift, largest blob
area, every box and centre, zone result, recent hit count, confirmation state,
timing, and periodic internal-heap/PSRAM readings. A newly confirmed result
also prints `MOTION TRIGGER`. If MQTT is enabled, confirmation drives the
existing activation state publisher; the Pi remains responsible for its own
active-session policy.

### Stage 2B test sequence

1. Let the empty scene settle for several scans. Expect no continuing boxes.
2. Walk into the orange zone from each edge and confirm a cyan box follows the
   changed region and `MOTION TRIGGER` appears after two of four positive scans.
3. Stand still, then move again. Pure motion should settle while stationary and
   respond to renewed movement.
4. Switch the room lights. Expect `illumination_change=true`, no accepted boxes,
   and no new confirmed trigger from that scan.
5. Repeat at close/horizontal, distant/oblique, and high/downward positions.
   Record `changed_pct`, box area, `scene_ms`, and whether each entry confirmed.

Motion mode's explicitly allocated workspace is 950,400 bytes at the default
VGA/grid settings: 921,600 bytes for decoded RGB888 plus 28,800 bytes for two
grayscale frames, two masks, and the connected-component queue. Boot logs
report the allocator-observed detector delta and remaining memory. Final scan
rate, sensitivity, and false-positive conclusions require the physical tests
above; they cannot be established by a desktop build alone.

## Stage 2C strength and shadow experiment

Stage 2C keeps the Stage 2B geometry and buffers. For every meaningful blob it
also compares horizontal/vertical gradient magnitude between the current and
previous 80x60 grayscale grids. This inexpensive structure signal is computed
only while visiting blob cells; it adds no image buffer.

A localised accepted in-zone blob confirms immediately when its changed-cell
fraction is at least 1.2 percent, mean luminance difference is at least 28,
mean gradient difference is at least 9, and its bounding rectangle covers no
more than 45 percent of the frame. Other accepted in-zone motion retains the
2-of-4 path. There is no candidate hold: immediate confirmation already solves
the strong enter-then-freeze case without extending weak noise into later
scans.

A local blob with mean luminance change of at least 20 but mean gradient
change below 6 is marked as a likely shadow and does not enter confirmation.
The browser draws these rejected candidates as purple dashed boxes; accepted
motion remains cyan. Serial and JSON diagnostics report luminance/structure
values, strong/shadow classification, and a confirmation reason. Thresholds
are initial test values in `main/stage2b_config.h`, not final museum tuning.

The only planned persistent memory increase is approximately 2 KB for the
larger HTTP-server task stack used to format the richer diagnostic JSON.
Record `processing_ms`, `scene_hz`, and the periodic free-memory logs before
and after flashing to measure the actual device cost.

## Stage 3A browser trigger-zone calibration (historical format)

The trigger rectangle is now runtime configuration rather than a compiled-only
value. `TriggerZoneConfig` owns the normalized `x/y/w/h` rectangle and stores a
versioned, checksummed 28-byte record in the existing NVS partition under the
`bwm_config` namespace. Missing, corrupt, non-finite, out-of-range, or smaller
than 5 percent rectangles fall back to the compiled central default. An NVS
failure disables saving but does not stop detection.

The preview exposes same-origin JSON routes:

- `GET /api/config/trigger-zone` returns the active rectangle.
- `POST /api/config/trigger-zone` validates and applies a rectangle in memory.
- `POST /api/config/trigger-zone/save` commits the active rectangle to NVS.
- `POST /api/config/trigger-zone/reset` applies the default without saving it.

Select **Edit Trigger Zone** to drag the rectangle or resize it from four corner
handles. Browser pointer coordinates are divided by the currently displayed
camera-image dimensions and converted to normalized coordinates. **Apply**
changes the detector immediately but remains unsaved. **Save** applies and
persists. **Cancel** reapplies the rectangle captured on entering edit mode,
including after an Apply. **Reset to Default** is immediate but deliberately
requires Save before it survives reboot.

No external JavaScript or CSS dependency is used. Current Chromium, Firefox,
and Safari-family browsers with Pointer Events and object-spread support are
expected; very old embedded browsers are not targeted. The Stage 3A API adds
no image buffer and leaves the existing 8 KB HTTP task stack unchanged. NVS
adds only its small handle/mutex plus the 28-byte record; the larger embedded
HTML primarily affects flash. Build-time image size and device free-memory
deltas must be recorded after compiling and flashing.

## Stage 3B polygon trigger geometry (reverted experiment)

Stage 3B replaces the rectangle model with one shared polygon representation:
a required inclusion polygon and an optional exclusion polygon, each containing
3–8 normalized full-frame points. The default Stage 3A rectangle is represented
as an ordinary four-point inclusion polygon. The exclusion polygon has an
explicit enabled flag and retains its points while disabled.

The detector continues to test only the motion-box centre. It accepts the
centre when it is inside inclusion and not inside an enabled exclusion polygon.
Both zones use the same boundary-inclusive ray-casting test. No box overlap,
polygon clipping, or image-processing behaviour changed.

The existing API routes remain, with payloads shaped as:

```json
{
  "trigger_geometry": {
    "inclusion": [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}],
    "exclusion": {
      "enabled": false,
      "points": [{"x": 0.4, "y": 0.4}, {"x": 0.6, "y": 0.4}, {"x": 0.6, "y": 0.6}]
    }
  }
}
```

The browser uses a lightweight inline SVG. Select inclusion or exclusion,
drag individual vertices, add a midpoint to the selected (or longest) edge,
and remove the selected vertex. Counts are constrained to 3–8. Exclusion is
enabled independently. Apply, Save, Cancel, and Reset retain their Stage 3A
semantics, and the cyan motion and purple shadow overlays remain visible.

Validation is server-authoritative and rejects non-finite/out-of-frame points,
adjacent duplicates or near-zero edges, polygons below the minimum area,
self-intersecting edges, and invalid counts. A complete geometry is validated
before it can replace the active copy.

NVS record version 2 stores both fixed-capacity polygons, counts, exclusion
state, and checksum in 144 bytes. At boot, a valid Stage 3A version-1 rectangle
is migrated in memory to four inclusion vertices with exclusion disabled; the
next explicit Save writes version 2. Missing, corrupt, or invalid data still
falls back to defaults.

The runtime geometry is about 140 bytes plus the existing mutex/NVS handle.
There are no new camera, grayscale, or PSRAM buffers, and the HTTP task remains
at 8 KB. The main task stack is raised from the ESP-IDF default 3584 bytes to
6144 bytes because Wi-Fi startup overflowed the default once Stage 3B geometry
state was live. The inline SVG/JavaScript and validation code increase flash; use
`idf.py size` and the existing boot/periodic heap logs for the exact build and
device deltas.

The verified ESP-IDF 5.5.5 motion build is 1,078,352 bytes (`0x107450`), leaving
74 percent of the 4 MB application partition free. This is 38,992 bytes above
the last recorded Stage 2B image, a combined delta that also includes the
intervening Stage 2C and Stage 3A features; it is not an isolated Stage 3B delta.

The polygon experiment was reverted after device testing because its SVG
vertex controls were not reliably draggable in the installation browser. The
current firmware again uses the proven Stage 3A rectangle editor and 28-byte
version-1 NVS record. If a version-2 polygon record was saved, boot converts
the inclusion polygon's bounds into a rectangle; the next Save writes version
1. The 6144-byte main stack and HTTP connection safeguards remain: browser
frame/status requests cannot overlap, refresh runs once per second, the server
allows four client sockets, and least-recently-used session purging is enabled.
The verified rollback build is 1,061,360 bytes (`0x1031f0`), leaving 75 percent
of the 4 MB application partition free.

## Stage 4 ESP-to-Pi activation test

The browser now includes **Send Test Activation**. Its POST
`/api/test/activation` request bypasses only camera detection and calls the
same envelope builder and MQTT publisher used by a newly confirmed camera
result. Every click creates one new event ID and publishes:

```text
topic: bwm/installation/activation
QoS: 1
retained: false
{"version":1,"id":"<uuid>","type":"installation.activation",
 "origin":"person_detector","timestamp":"<ISO-8601>",
 "payload":{"state":"active"}}
```

Camera publishing is now activation-only: one event is emitted on each
inactive-to-confirmed edge. Returning to unconfirmed rearms the next edge but
does not publish `inactive`, because the Translation Pi owns the admitted
session's ten-minute lifetime. Manual clicks always emit a fresh event and do
not alter camera edge state.

The ESP serial log identifies `source=manual_test` or
`source=camera_confirmation`, event ID, type, origin, timestamp, topic, MQTT
message ID, and current connection state. A disabled/unavailable MQTT client
returns HTTP 503 to the browser and logs why no event was queued.

The Translation production runtime remains initially active by default. For
this Stage 4 test, use the existing semantic `inactive` test control to end
that initial session and enter the normal hardware-quiescent admission state.
Its ordinary shared MQTT client subscribes to the same topic, validates the
common envelope, and routes it through the existing semantic ingress. Console
diagnostics distinguish
receipt, envelope validation, duplicate ID rejection, admission, an activation
ignored while already active, session start, teardown, and the return to
hardware-quiescent idle.

For the physical test, the Pi and ESP must use the same reachable broker. The
Pi's checked-in `configs/mqtt.yaml` uses a broker on the Pi itself
(`localhost:1883`), so the ESP deployment-local `mqtt_config.h` should use
the Pi's LAN address, for example:

```cpp
#define BWM_MQTT_BROKER_URI "mqtt://192.168.1.50:1883"
#define BWM_MQTT_TOPIC_BASE "bwm"
```

Run the normal Translation runtime on the Pi and wait for
`[MQTT] CONNECTED`. From a second terminal, use the existing semantic test
control to end the initially active session without changing production
configuration:

```bash
python translation/tools/simulate_person_activation.py inactive
```

Wait for `[Session] IDLE: session state cleared; hardware quiescent`, then
use the browser button. The first event should log
`admitted_session_started`; another click during the session should log
`ignored_already_active` and must not reset its start time. To use the
existing semantic test control to end the session without shortening
production timeout settings, run from the repository root:

```bash
python translation/tools/simulate_person_activation.py inactive
```

Wait for `[Session] IDLE: session state cleared; hardware quiescent`, click
again and expect another admission. Finally, let camera confirmation generate
the event and compare the ESP log's `source=camera_confirmation` with the
same Pi receipt/admission sequence. The ESP timestamp requires valid wall-clock
time on the board to be meaningful; admission and deduplication use the event
ID and do not depend on timestamp freshness.

## Stage 5 runtime Wi-Fi provisioning

Wi-Fi credentials are no longer compiled into the firmware. They are stored in
the dedicated `bwm_wifi` NVS namespace, separate from the trigger-zone record.
The ESP-IDF Wi-Fi driver's own credential storage is set to RAM so an unverified
password is not silently persisted by the SDK. Stage 5 writes the SSID and
password to `bwm_wifi` only after the station obtains an IP address, then
restarts into the normal runtime.

Boot follows this flow:

1. With valid saved credentials, the node joins that network and starts the
   existing camera page and MQTT client unchanged.
2. With no saved credentials, it immediately starts a WPA2 setup AP named
   `BWM-Vision-xxxxxx` (the suffix identifies the board).
3. If a saved network is unavailable, it makes five connection attempts,
   separated by three seconds, then enters recovery without deleting or
   replacing the saved credentials.

Connect a phone or laptop to the setup AP with password `bwm-setup`, then open
`http://192.168.4.1/`. The self-contained setup page scans nearby 2.4 GHz
networks, allows manual SSID entry for hidden networks, accepts a password, and
reports whether the connection test succeeded. The AP remains available while
the connection is tested. On success the response confirms that credentials
were saved, and the node restarts after a short delay. Rejoin the venue network
and use the station IP printed in the serial log.

The normal camera page includes **Forget Wi-Fi / Change Venue**. After
confirmation it erases only the `bwm_wifi` namespace and restarts; the trigger
zone is preserved and the setup AP returns. Erasing the board's NVS also gives
the expected fresh-device setup flow.

During temporary station loss, the ESP first retries at three-second intervals.
After five failed attempts it enters recovery in simultaneous AP/station mode.
The `BWM-Vision-xxxxxx` AP remains available at `http://192.168.4.1/`, but it
serves the normal camera, trigger-zone, manual-activation, and diagnostics page
rather than the credential-entry page. The diagnostic block immediately below
the preview identifies the Wi-Fi/MQTT outage and counts down to the next retry.
Detection continues locally, and **Forget Wi-Fi / Change Venue** remains
available if the network really has changed.

Recovery attempts the retained venue SSID once every five minutes. A successful
station connection clears recovery, lets the existing MQTT client reconnect,
and switches Wi-Fi back to station-only mode so the temporary AP disappears.
No reboot is required. Failed recovery attempts neither clear NVS nor start a
rapid retry loop. Missing credentials remain a distinct provisioning state and
continue to serve only the setup page.

The ESP MQTT client keeps its existing reconnect behaviour; detection,
confirmation, preview buffering, trigger-zone persistence, event topic,
envelope, and activation edge semantics are unchanged.

The setup implementation adds one persistent manager object (roughly a few
hundred bytes), an event group, inline HTML/JavaScript, and temporary 3 KB
reconnect or 2 KB restart task stacks. Stage 5B adds a 3 KB recovery task stack;
the task blocks between state changes/retries and performs no tight polling.
Network scanning uses bounded local arrays and the existing HTTP task. It adds
no camera or detector PSRAM buffers. The verified ESP-IDF 5.5.5 Stage 5B image
is 984,768 bytes (`0xf06c0`), leaving 77 percent of the 4 MB application
partition free. Static D/IRAM use is 131,563 bytes; the recovery task's 3 KB
stack is allocated dynamically only after recovery is first needed. The earlier
Stage 5 image was 981,024 bytes (`0xef820`).

Venue limitations remain: the ESP32-S3 supports 2.4 GHz Wi-Fi, not 5 GHz-only
networks; this page supports open and ordinary personal-password networks, not
enterprise/802.1X credentials or captive-portal acceptance. The configured
MQTT broker must be reachable from the venue WLAN. Client isolation, firewalls,
separate VLANs, or a changed Pi address can still prevent MQTT even when Wi-Fi
association succeeds. Credentials are protected over the WPA2 setup AP but are
plain NVS strings unless flash encryption/NVS encryption is enabled for the
deployed device.
