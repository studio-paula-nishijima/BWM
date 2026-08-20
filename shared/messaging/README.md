# BWM semantic messaging

`shared.messaging` is repo-wide infrastructure. Translation, the person
detector, and later whisper/oracle code may use it without importing one
another's runtime internals.

Each message is compact JSON with `version`, `id`, `type`, `origin`,
`timestamp`, and object `payload`. IDs are UUIDs; origins name the emitting
component (for example `person_detector`). The Stage 6 event is
`installation.activation`, with payload `{ "state": "active" }` or
`{ "state": "inactive" }` on `bwm/installation/activation`.

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

## Subsystem handoffs

The ESP-IDF person detector deliberately remains responsible for deciding its
own activation condition. Its next adapter should publish this exact envelope
and topic, with a new ID on each explicit state publication and origin
`person_detector`; it must not issue Translation commands or rely on repeated
detections extending a session.

Whisper/oracle work should reuse this package and configuration, consume the
installation activation state if required, and later add semantic event types
such as `question.detected` or `response.ready`. It must not add hardware
commands to the shared protocol.
