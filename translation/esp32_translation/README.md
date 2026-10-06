# BWM autonomous ESP32-S3 Translation controller

This is the full, autonomous Translation runtime for one ESP32-S3. It is a
separate PlatformIO project; `esp32_tuesday_fallback/` remains unchanged and
independently deployable.

The firmware owns session state, indexed random score selection, six-channel
playback, Voice reaction selection, actuator safety, a local activation button,
BLE-central ingress from BWM Vision, MQTT ingress through an external broker,
and the semantic UART link to Whisper. BLE, MQTT, UART, and local input all feed
one validation/deduplication path. Transport loss never changes installation
state.

Arduino/PlatformIO is retained deliberately. The separate live-tested XIAO
fallback provides low-level evidence for the GPIO initialization sequence,
static flash table, and non-blocking millisecond scheduler. ESP32 Arduino also
provides BLE central, Wi-Fi/MQTT, Preferences/NVS, hardware UART, and the IDF
watchdog used here. Moving the proven actuator path to ESP-IDF would add porting
risk without improving exhibition behavior.

## Hardware profiles

The only full-controller target is ESP32-S3-DevKitC-1 with an
ESP32-S3-WROOM-1-N16R8 module: 16 MB Quad-SPI flash and 8 MB Octal-SPI PSRAM.
All signals are 3.3 V logic. The Whisper UART is 115200 baud, 8-N-1.

| Function | DevKitC-1 header GPIO |
|---|---:|
| Solenoid 1 | GPIO4 |
| Solenoid 2 | GPIO5 |
| Solenoid 3 | GPIO6 |
| Solenoid 4 | GPIO7 |
| Solenoid 5 | GPIO15 |
| Solenoid 6 | GPIO16 |
| Active-low local button | GPIO17 |
| UART TX to Whisper RX | GPIO18 |
| UART RX from Whisper TX | GPIO8 |

This contiguous J1-header allocation is independent of Raspberry Pi BCM and
XIAO pin numbering. It avoids strapping GPIO0/3/45/46, native USB/JTAG
GPIO19/20, USB-to-UART/programming GPIO43/44, JTAG GPIO39-42, revision-dependent
RGB LED GPIO38/48, and flash/Octal-PSRAM GPIO26-37. The dedicated PlatformIO
board definition selects `qio_opi`, `default_16MB.csv`, `BOARD_HAS_PSRAM`, and
the 16 MB upload geometry. Firmware also refuses to operate unless runtime
flash is exactly 16 MB and allocator-visible PSRAM confirms the 8 MB capacity
class (Arduino reports slightly less than the raw device size).

The XIAO ESP32-S3 Sense remains only the independent minimal Tuesday fallback
under `esp32_tuesday_fallback/`; this full-controller project does not build a
XIAO image.

Software cannot guarantee LOW before firmware executes. Effective external
MOSFET gate pull-downs, common control ground, backfeed checks, and the staged
electrical bring-up documented by the fallback remain mandatory. Every output
is preloaded LOW, configured as OUTPUT, and reaffirmed LOW as the first setup
operation.

## Score/config generation

Generation remains host-side:

```text
LamaH source -> translate_lamah.py -> events.npy -> tools/export_score.py
             -> generated/events.csv + score_data.h + artistic_config.h
```

The exporter validates every real record, applies the tracked 2003-01-01
through 2017-12-31 inclusive playback filter, maps the ordered configured
solenoids to compact channels, uses deterministic half-up millisecond
quantization, and embeds source/config SHA-256 provenance. Unsupported data is
a hard failure. The MCU neither parses NumPy/YAML nor mutates the score.

Regenerate from this directory with the shared base Translation environment:

```powershell
& 'C:\Users\mail\Documents\ChatGPT\New project\BWM-review\translation\translation_venv\Scripts\python.exe' tools\export_score.py
& 'C:\Users\mail\Documents\ChatGPT\New project\BWM-review\translation\translation_venv\Scripts\python.exe' tools\simulate_safety.py
```

At each genuine idle-to-active transition the firmware uniformly selects a
source start in `0..duration-600000 ms`, uses binary search to form the
half-open interval, and stores only begin/end indexes plus the first selected
event's timestamp. Due times are rebased to that first selected event without
copying the table. The session wall clock starts at activation; solenoid
admission opens 4000 ms later and timeout remains 600000 ms after activation.

## Session and reaction behavior

`active -> active` and `inactive -> inactive` are no-ops. Teardown increments a
generation, closes admission, clears bounded scheduled work and reaction busy
state, clears selection, and forces all outputs LOW. A scheduled item with an
old generation cannot actuate.

The default trigger mode is `whisper.interaction`. Detector values select the
five tracked Silero bands; button occurrences use the tracked equal-weight
policy. `whisper.state` is still validated and recorded. Change the single
build-time `kTriggerMode` only for the mutually exclusive compatibility mode,
where a transition into `capture_processing` triggers and same-state messages
do not. One external reaction is busy at a time; new occurrences are dropped.

Implemented generated behavior is:

- simultaneous-then-sequence: 0.5 s quiet gap, all six at 150 ms, 0.5 s wait,
  ordered six at 0.2 s spacing, 1.0 s tail;
- cascade: 0.5 s quiet gap, ordered six at 0.3 s spacing, 1.0 s tail;
- split groups: 0.5 s quiet gap, channels 1-3, 2.0 s wait, channels 4-6,
  2.0 s tail;
- triple tap: 3.0 s replacement window, three taps at 0.2 s start spacing;
- double tap: 3.0 s replacement window, two taps at 0.4 s start spacing.

Override windows discard due base events while score time continues. Repeat
windows replace each due event. Per-channel pulse work is serialized, matching
the Pi GPIO worker behavior; independent channels remain simultaneous.

## Semantic transports

Accepted envelopes are schema version 1 with non-empty ID/type/origin, an
ISO-like UTC timestamp, and object payload. One 1024-entry/3600-second recent-ID
cache is shared across BLE, MQTT, and UART. Duplicate delivery of the same ID is
therefore applied once.

- BLE central scans for service
  `7a9e4c10-5b8d-4bd6-9c17-2f3e8a4b1001`, subscribes to characteristic
  `...1002`, and implements the documented flags/uint16 sequence framing.
  Disconnect only causes rescan; it never synthesizes inactive.
- MQTT subscribes at QoS 1 to `bwm/installation/activation`,
  `bwm/whisper/state`, and `bwm/whisper/interaction`. It is a client and never a
  broker. Wi-Fi/broker failure is isolated from BLE/local/UART operation.
- UART accepts partial and multiple newline-delimited frames up to 8192 bytes.
  Malformed/oversized input is discarded through the next newline. Actual
  local state transitions emit a fresh `installation.activation` event with
  wire origin `translation_pi`; inbound UART activation is not echoed. Startup
  state synchronization is best effort.

NTP supplies UTC when Wi-Fi permits. Without civil time, outgoing events use a
schema-valid deterministic 1970-based uptime timestamp and diagnostics report
`timestamp_quality=monotonic_fallback`; this never blocks operation.

## Deployment settings

Tracked defaults contain no credentials and leave Wi-Fi/MQTT disabled. Copy
`firmware/include/deployment_config.h.example` to the ignored
`deployment_config.h`, or provision the ESP NVS namespace `bwm` with:

| NVS key | Type | Default |
|---|---|---|
| `wifi_ssid` | string | empty |
| `wifi_password` | string | empty |
| `mqtt_host` | string | empty (external broker required) |
| `mqtt_port` | uint16 | 1883 |

NVS values override compiled defaults. MQTT availability is optional; a venue
broker address must replace the Pi-only `localhost` value.

## Safety and watchdog

All base and reaction pulses cross one actuator boundary. Fixed storage is 256
pending pulses; exhaustion is a latched fault. The independent safety service
runs before admissions and maintains both requested and hard OFF deadlines.

Full-controller emergency constants (not changes to the fallback) are:

- 6 valid channels; 500 ms hard maximum pulse;
- 40 ms minimum OFF, allowing the configured triple-tap's approximately 50 ms;
- per channel, at most 160 admitted pulses and 9000 ms requested ON in a
  rolling 10-second bounded history;
- malformed internal work, queue exhaustion, or explicit internal fault stops
  admission, clears work, forces all outputs LOW, and latches the fault.

The main controller task is registered with the ESP task watchdog at 8 seconds.
Watchdog/reset safety still depends on external gate pull-downs until the
earliest firmware LOW sequence runs.

Serial diagnostics are connection-gated and summary-only every 30 seconds plus
transitions/faults; an absent serial consumer can never block the watchdog.
No per-pulse logging is enabled. Summaries include session/reaction/transport
state, BLE notification and complete-message counters, accepted/rejected
pulses, invalid/duplicate messages, and fault status.

## Build and test

```powershell
# Host exporter/simulation tests, from translation/
& 'C:\Users\mail\Documents\ChatGPT\New project\BWM-review\translation\translation_venv\Scripts\python.exe' -m pytest -q esp32_translation\tests esp32_tuesday_fallback\tests

# Portable C++ core tests and the N16R8 firmware, from esp32_translation/
& 'C:\Users\mail\.platformio\penv\Scripts\pio.exe' test -e native
& 'C:\Users\mail\.platformio\penv\Scripts\pio.exe' run -e devkitc_n16r8
```

The safety simulation runs the complete filtered canonical score and every
current reaction repeatedly across that score. See `generated/safety_report.md`.

## Deliberate practical loss and validation status

Halo/DMX is not implemented. The Pi's OLA/olad/FTDI path requires Linux and an
external USB adapter; no theoretical DMX or RS-485 replacement is included.

The separate observed hardware baseline is the XIAO fallback driving all six
live solenoid channels stably. This full controller targets only the DevKitC-1
/ WROOM-1-N16R8. Session transitions/random selection,
button input, reaction timing/cancellation, BLE central, UART, optional MQTT,
watchdog recovery, and long-duration integrated operation still require the
targeted hardware validation described in the implementation brief. If any
output map or low-level safety code is changed, restart the full cautious
electrical bring-up sequence.
