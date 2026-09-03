# BWM semantic messaging

`shared.messaging` is repo-wide infrastructure. Translation, the person
detector, and the Voice/Oracle runtime use it without importing one
another's runtime internals.

Messaging transport is not runtime lifecycle control. Translation and
Voice/Whisper boot and operate independently of each other, the person
detector, MQTT, UART, and remote-peer health. MQTT and UART are sibling
transports for a transport-neutral semantic envelope: one event may fan out
over both with the same ID, origin, timestamp, type, and payload, and a
receiver deduplicates once at semantic ingress. The origin names the producing
subsystem, not a transport. Transport absence or failure is isolated
degradation; it never implies semantic `inactive`, activation, or quiescence.
Do not derive activation or quiescence from a heartbeat or from a missing
message.

Each message is compact JSON with `version`, `id`, `type`, `origin`,
`timestamp`, and object `payload`. IDs are UUIDs; origins name the emitting
component (for example `person_detector`). The Stage 6 event is
`installation.activation`, with payload `{ "state": "active" }` or
`{ "state": "inactive" }` on `bwm/installation/activation`. In the
inter-Pi deployment, this is **Translation activation** when its origin is
`translation_pi`: Translation's authoritative installation state.

Voice/oracle components publish **Voice lifecycle** as `voice.state` on `bwm/voice/state`, with
payload `{ "state": "idle|initializing|listening|whisper_detected|capture_processing|response_displayed" }`.
Each publication uses a fresh envelope ID and a meaningful origin such as
`voice_pi`. These are coarse semantic milestones, not detector scores, ASR,
retrieval, display, servo, GPIO, or Translation strategy commands. Receivers
must validate the state and suppress duplicate IDs before interpreting a
state transition.

Messages describe semantic state, never GPIO, systemd, UART, or module
commands. Receivers use a bounded TTL/LRU ID cache and must also make an
`active` state idempotent. This makes the envelope reusable if a future UART
bridge duplicates an IP delivery.

MQTT uses QoS 1 for local control: delivery is retried but duplicate delivery
is expected and harmless. Activation messages are deliberately non-retained:
a restart/resubscribe must not start a stale ten-minute session. The optional
connection wrapper uses paho-mqtt's one blocking network-loop thread with
bounded reconnect delay (2–30 seconds), so it neither busy-spins nor gates
local operation.

The initial common namespace also reserves `bwm/system/status/<origin>` for a
future availability/LWT convention. It does not yet impose a health protocol.

## Voice interaction occurrence

**Voice interaction** is published as `voice.interaction` on `bwm/voice/interaction` only for a real
post-confirmation, post-cooldown occurrence. Detector payloads are `{ "source":
"detector", "silero_selection_value": <float> }`; button payloads are
`{ "source": "button" }`. The value is an artistic selector from the
authoritative final ten-frame Silero window, not calibrated confidence,
loudness, speaker identity, or a physical command. One `SemanticEvent` object
is reused unchanged across MQTT and UART fan-out.
Availability information is not an instruction to activate, deactivate, or
quiesce another subsystem.

## Subsystem handoffs

The ESP-IDF person detector deliberately remains responsible for deciding its
own activation condition. Its next adapter should publish this exact envelope
and topic, with a new ID on each explicit state publication and origin
`person_detector`; it must not issue Translation commands or rely on repeated
detections extending a session.

The Voice runtime publishes the five `voice.state` lifecycle milestones above using this
package. Translation's initial behavior reacts to a transition into
`capture_processing`; Voice does not select or need to know the solenoid
reaction, nor whether Translation is currently busy. Future UART redundancy
must preserve the same IDs/origins so duplicate transport delivery resolves to
one semantic transition.

## Stage 8 UART transport

MQTT and UART carry the identical semantic envelope. Emitters create one
`SemanticEvent` and may fan that exact object out through both transports; its
ID, origin, timestamp, type, and payload never change. Receivers validate then
deduplicate at semantic ingress, so delivery of the same ID by MQTT and UART
executes application behaviour once. Received events are never blindly
forwarded, preventing loops.

Whether UART is enabled by default is a deployment/configuration choice, not
a semantic requirement. The same event and receiver behaviour apply to
UART-only, MQTT-only, and redundant MQTT-plus-UART deployments. Dual transport
is for delivery redundancy; it does not create two application events.

## BLE activation transport

Translation can optionally receive person-detector activation envelopes over
BLE. The ESP is the `BWM Vision` peripheral/GATT server; Translation is the
central/client. `SemanticBLETransport` reassembles the documented notification
fragments, parses the normal `SemanticEvent`, and calls
`TranslationSemanticIngress.handle_event`. It contains no installation or
session policy. The ingress therefore shares its ID cache across BLE, MQTT and
UART: an event delivered over BLE and MQTT with the same ID is interpreted once.

BLE is configured in `configs/mqtt.yaml`. The process starts independently of
the ESP; a scan failure, disconnect, or missing notification only degrades this
transport and never synthesizes an inactive installation state. It reconnects
and resubscribes after a disconnect, including when the ESP appears only after
Translation is running. There is no Pi-to-ESP activation-state feedback.

P1 deliberately contains no MQTT-to-BLE fallback policy and no coupling to
Wi-Fi recovery timing: MQTT and BLE are independent ingress siblings. A later
detector-side P2 stage may prefer MQTT and fall back to BLE when Wi-Fi/MQTT is
unavailable. During that handover it must preserve a semantic event's ID;
Translation's shared ingress then deduplicates MQTT-first and BLE-first
delivery. For UUIDs, framing, and a hardware diagnostic, see
`person_detector/BLE_ACTIVATION_CONTRACT.md`.

UART frames are compact UTF-8 JSON followed by a newline: default 115200 8N1,
0.25-second read timeout, and 8192-byte maximum. Partial/multiple frames work;
malformed or oversized frames are discarded through their next newline and
parsing recovers. GPIO14/15 resolve dynamically from DT alias `uart0`, never
`/dev/serial0`. The observed Pi 5 result is `/dev/ttyAMA0`; `/dev/serial0` can
be debug `/dev/ttyAMA10`. Startup rejects kernel-console or serial-getty
ownership of the resolved device.

Wire 3.3 V TTL: Translation GPIO14 TX -> Voice GPIO15 RX; Translation GPIO15
RX <- Voice GPIO14 TX; Translation GND <-> Voice GND. No flow control.
