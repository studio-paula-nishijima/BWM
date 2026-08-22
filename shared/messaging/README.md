# BWM semantic messaging

`shared.messaging` is repo-wide infrastructure. Translation, the person
detector, and the Voice/Oracle runtime use it without importing one
another's runtime internals.

Each message is compact JSON with `version`, `id`, `type`, `origin`,
`timestamp`, and object `payload`. IDs are UUIDs; origins name the emitting
component (for example `person_detector`). The Stage 6 event is
`installation.activation`, with payload `{ "state": "active" }` or
`{ "state": "inactive" }` on `bwm/installation/activation`.

Voice/oracle components publish `voice.state` on `bwm/voice/state`, with
payload `{ "state": "idle|listening|whisper_detected|capture_processing|response_displayed" }`.
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

## Subsystem handoffs

The ESP-IDF person detector deliberately remains responsible for deciding its
own activation condition. Its next adapter should publish this exact envelope
and topic, with a new ID on each explicit state publication and origin
`person_detector`; it must not issue Translation commands or rely on repeated
detections extending a session.

The Voice runtime publishes the five `voice.state` milestones above using this
package. Translation's initial behavior reacts to a transition into
`capture_processing`; Voice does not select or need to know the solenoid
reaction, nor whether Translation is currently busy. Future UART redundancy
must preserve the same IDs/origins so duplicate transport delivery resolves to
one semantic transition.
