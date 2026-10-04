# BWM Translation — disposable Tuesday ESP32 fallback

This subtree is an isolated exhibition fallback for deterministic playback of
the canonical Translation score on a Seeed XIAO ESP32-S3 Sense. It is not a
Translation runtime port. It has no network, camera, BLE, UART, activation,
random-segment, dynamic-score, filesystem, or NumPy functionality on the
microcontroller. Normal Translation source and configuration are untouched.

The host converts `translation/events.npy` once into an inspectable CSV and a
small static C++ table. The firmware schedules that table non-blockingly, so
events on different channels can overlap.

## Stop: electrical prerequisites

The firmware cannot hold a GPIO LOW before it starts executing. **Before
connecting the XIAO to the MOSFET board, verify an effective hardware pull-down
from every MOSFET gate input to control-stage ground.** If reliable pull-downs
are absent, add suitable external gate pull-down resistors first. Do not count
the ESP32's software pin state as reset-time protection.

- Connect XIAO GND to MOSFET control-stage GND.
- Drive only MOSFET gate/control inputs. Never drive solenoids from XIAO GPIO.
- Never connect a 12 V rail to the XIAO.
- With the controller unpowered, check that the interface does not backfeed a
  GPIO. Stop hardware bring-up if any unexpected voltage is present.
- This fallback does not change the existing flyback or supply topology.

Gate pull-down status is currently **NOT VERIFIED**. Physical connection is
prohibited until it is verified at the hardware.

## Pin mapping

The mapping follows Seeed's current [XIAO ESP32-S3 hardware overview](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/#hardware-overview).
That official table maps D0/D1/D2/D3/D4/D5/D8 to
GPIO1/GPIO2/GPIO3/GPIO4/GPIO5/GPIO6/GPIO7. The same page identifies GPIO3 as a
reset strapping input controlling the JTAG signal source, so this fallback
deliberately skips D2/GPIO3. It also avoids GPIO0/BOOT, USB pins, and all Sense
camera-internal signals. The attached Sense camera is not initialized.

| Score target | Channel | XIAO pin | ESP32-S3 GPIO |
|---|---:|---|---:|
| `solenoid_1` | 0 | D0 | 1 |
| `solenoid_2` | 1 | D1 | 2 |
| `solenoid_3` | 2 | D3 | 4 |
| `solenoid_4` | 3 | D4 | 5 |
| `solenoid_5` | 4 | D5 | 6 |
| `solenoid_6` | 5 | D8 | 7 |

D4/D5 and D8 have alternate I2C/SPI functions, but this standalone firmware
does not enable those buses. Confirm the physical silkscreen labels before
wiring; channel numbers are zero-based in generated files and firmware.

## Canonical score inspection

The committed `translation/events.npy` inspected for this fallback has:

- shape `(6253,)`; 6,253 events; each event is a Python `dict`;
- fields `action`, `duration`, `metadata`, `playback_time`, `target`,
  `timestamp`, and `type`;
- only `type=solenoid`, `action=pulse`, and targets `solenoid_1` through
  `solenoid_6`;
- metadata fields `frequency` and `source_value` (reported but not used);
- source SHA-256
  `e71e0317828fd01cc253b7ecbe5a09ae10dfdfe9525ba3ca39fce69154da0a9e`;
- raw playback range 3.751114894–3107.038757142 s;
- rebased, quantized last event onset 3,103,288 ms (3,103.288 s);
- pulse range 150–150 ms;
- maximum timing quantization error 0.499813 ms;
- no malformed or unexpected records.

Per-target counts:

| Target | Events |
|---|---:|
| `solenoid_1` | 643 |
| `solenoid_2` | 891 |
| `solenoid_3` | 1,180 |
| `solenoid_4` | 1,166 |
| `solenoid_5` | 1,157 |
| `solenoid_6` | 1,216 |

The minimum raw same-channel start interval is 0.285714286 s, for a maximum
observed same-channel event rate of 3.5 Hz. After millisecond quantization, the
minimum OFF interval is 135 ms. Therefore the firmware's 100 ms minimum-OFF
rule rejects **zero** canonical events.

## Regenerate and inspect

From `translation/esp32_tuesday_fallback`, using the shared base Translation
environment:

```powershell
& 'C:\Users\mail\Documents\ChatGPT\New project\BWM-review\translation\translation_venv\Scripts\python.exe' tools\convert_events.py
```

On another prepared host, `python tools/convert_events.py` is equivalent. The
command loads and validates `../events.npy`, prints the full score/safety
report, and rewrites:

- `generated/events.csv` for human inspection;
- `generated/score_data.h` for direct compilation into flash.

Both outputs identify the canonical source, its SHA-256, and converter version.
They contain no generation timestamp, so identical input and converter code
produce byte-identical output. Do not hand-edit generated files. Regenerate
them whenever the canonical score changes.

The converter fails on an unreadable or non-1D NumPy score, a non-dictionary or
incomplete record, an unknown type/action/target, invalid time/duration,
over-500 ms pulse, numeric overflow, non-monotonic output, or a canonical event
that would violate the selected minimum-OFF backstop.

## Build, flash, and monitor

The project reuses the repository's proven Arduino/PlatformIO XIAO board
convention without importing the person-detector application. From `firmware`:

```powershell
& 'C:\Users\mail\.platformio\penv\Scripts\pio.exe' run -e xiao_esp32s3
& 'C:\Users\mail\.platformio\penv\Scripts\pio.exe' run -e xiao_esp32s3 -t upload --upload-port COMx
& 'C:\Users\mail\.platformio\penv\Scripts\pio.exe' device monitor --baud 115200 --port COMx
```

Replace `COMx` with the enumerated XIAO USB port. Build and playback need no
network after PlatformIO's toolchain dependencies are installed. Serial is
diagnostic only and is never awaited by playback.

## Independent firmware safety

Tracked fallback constants are new, fallback-local defaults; they do not alter
normal Translation or Pi deployment configuration:

- exactly 6 valid channels (`0..5`);
- 500 ms maximum admitted pulse;
- 100 ms minimum OFF interval per channel;
- 1,500 ms all-LOW loop gap;
- 115,200 baud diagnostics;
- no watchdog subsystem (hardware pull-downs plus earliest application LOW
  initialization provide simple, deterministic reset behavior).

Every accepted HIGH has its requested OFF deadline and `high_since_ms`
hard-limit reference established before the GPIO transition. A second check
forces a channel LOW after 500 ms even if normal score scheduling is wrong.
An event on an already-HIGH channel is rejected without extending or replacing
the existing deadline. Invalid compiled channel/duration data enters a latched
fault state: all outputs are driven LOW, playback stops, and a concise serial
fault is emitted. High-volume per-pulse output is disabled unless
`BWM_TUESDAY_DEBUG_PULSES=1` is added deliberately at build time.

After the final event, firmware waits for every bounded pulse to finish,
reasserts all outputs LOW, holds the loop gap, verifies the logical all-LOW
state, and restarts event zero without mutating the table.

## Tests

From `translation`:

```powershell
& 'C:\Users\mail\Documents\ChatGPT\New project\BWM-review\translation\translation_venv\Scripts\python.exe' -m pytest -q esp32_tuesday_fallback\tests
```

From `translation/esp32_tuesday_fallback/firmware`:

```powershell
& 'C:\Users\mail\.platformio\penv\Scripts\pio.exe' test -e native
```

If a native `gcc/g++` toolchain is unavailable, compile the identical C++ test
source for the XIAO without uploading or claiming execution:

```powershell
& 'C:\Users\mail\.platformio\penv\Scripts\pio.exe' test -e xiao_esp32s3 --without-uploading --without-testing
```

The host tests exercise mapping, the canonical file, all specified rejection
classes, sorting/rebasing, deterministic quantization, generated count
agreement, and minimum-OFF analysis. Native C++ tests exercise admission,
invalid channel and duration rejection, forced OFF, simultaneous channels,
all-LOW fault action, and clean post-gap restart.

## Mandatory staged bring-up log

Do not skip stages. Update this table during physical bring-up; `NOT RUN` is
intentional here because this software task did not have access to the board or
solenoid hardware.

| Stage/check | Status | Evidence/notes |
|---|---|---|
| Gate pull-down verified on all six inputs | **NOT RUN** | Must pass before connecting XIAO |
| Stage 1 — ESP32 only | **NOT RUN** | Check boot LOW, timing, simultaneous events, reset/reflash behavior |
| Stage 2 — gates connected, 12 V OFF | **NOT RUN** | Check reset LOW, no boot pulse, expected timing, no backfeed |
| Backfeed with controller unpowered | **NOT RUN** | Stop if any unexpected GPIO voltage exists |
| Stage 3 — one live channel | **NOT RUN** | Check mapping, pulse, temperature, USB stability, reset/noise |
| Stage 4 — one bank of three | **NOT RUN** | Check overlap, supply behavior, reset, cross-triggering |
| Stage 5 — all six channels | **NOT RUN** | Observe initial full playback carefully |
| Controller reset/brownout observed | **NOT RUN** | Record yes/no during each powered stage |
| Electrical anomaly observed | **NOT RUN** | Record measurements and stop on anomaly |

At Stage 1, use a logic analyzer or oscilloscope where possible. Confirm six
LOW outputs before relying on score timing. At Stage 2, keep every 12 V supply
off. At Stages 3–5, increase live load only after the preceding stage passes.
