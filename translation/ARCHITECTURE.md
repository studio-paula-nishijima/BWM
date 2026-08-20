# Translation architecture

Current base path:

`LamaH-CE -> event generation -> events.npy -> playback -> routing -> hardware`

`events.npy` is the persistent base score. The present system retains the released generator, score schema, playback ordering, and GPIO dispatch behaviour. Hardware topology is loaded from `configs/hardware.yaml`; its six current solenoids are not an architectural channel-count limit.

Implemented playback path:

`events.npy -> prepared events -> Playback Engine -> routing -> hardware`

The Playback Engine owns clock-driven event progression, position and lifecycle.
It receives already prepared events and dispatches each due event through an
injected router. Its single due-event dispatch boundary is the intended future
insertion point for runtime modulation; modulation itself is not implemented.

Target runtime path (partially implemented):

## Persistent activation runtime

The translation process initializes the prepared score, hardware backend, and
GPIO17 input once and remains alive while the installation is active or
inactive. Installation activation is application state, not a systemd
start/stop operation. `ActivationController` owns that state and translates
transport-independent `activate`, `deactivate`, and `toggle` commands into
`PlaybackEngine` resume/pause operations.

When inactive, logical score time is frozen: pending events are not made due,
no new base events are dispatched, and reactivation continues from the same
score position. The runtime blocks on a condition while inactive rather than
polling at playback cadence. The GPIO backend and prepared event data remain
initialized; no backend teardown/recreation occurs on deactivation. Existing
GPIO worker threads remain blocked on their queues and an already-issued pulse
is not redefined as an emergency cut-off.

GPIO17 is the independent local fallback activation adapter. It receives a
button edge and calls the same controller toggle command, without systemd,
MQTT, UART, networking, or the person detector. A future MQTT adapter will
call this same controller command surface:

`GPIO17 or future MQTT adapter -> ActivationController -> PlaybackEngine -> due base event -> future Runtime Modulation -> EventRouter -> hardware`

`button_service.py` and its service retain the old GPIO17-to-systemd
start/stop design and are superseded by this runtime path. They remain checked
in for deployment cleanup, but must not be run alongside the persistent
runtime. A later deployment change should keep `play-events.service` alive and
retire the legacy button service; no service files are changed here.

Completion remains terminal: toggling activation after a completed score does
not replay it. Persistent exhibition behaviour after completion (hold, select
a new score, or restart under a separate policy) remains a later lifecycle
decision.

Target runtime path (documented only):

`events.npy -> Playback Engine -> Runtime Modulation Engine -> runtime safety/scheduling -> hardware`

The future Runtime Modulation Engine remains generic: it may support overlays/insertion, interruption, event transformation, suppression/filtering, parameter modulation, and strategies not yet anticipated. Cascades and multi-tap patterns are configurations/strategies using that layer, not architectural primitives.

Future external-event path (documented only):

`BWM semantic event layer -> translation-side policy/commands -> Runtime Modulation Engine`

Future compatibility includes shared semantic MQTT events, an MQTT-to-UART transport bridge, UART reservation on GPIO14/15, person-detector installation activation, GPIO17 as the local activation fallback, whisper/oracle semantic interaction and question events, a separate Voice Pi backup interaction button, and message IDs/origin metadata for transport deduplication. None is implemented in this stage.

## Future UART inter-Pi transport

GPIO14/TXD0 and GPIO15/RXD0 are reserved as the intended physical UART pins for the BWM inter-Pi transport. On the current Raspberry Pi 5 configuration, those pins are provided by RP1 UART0.

The future UART transport/bridge layer must resolve the device-tree `uart0` alias at runtime, derive the corresponding `/dev/tty*` node explicitly, and open that resolved node. It must not use `/dev/serial0` as the BWM transport selector: on the tested Pi 5 configuration, `/dev/serial0` resolves to `/dev/ttyAMA10`, the debug UART, while GPIO14/15 resolve to `/dev/ttyAMA0`. `/dev/ttyAMA0` is an observed mapping on that configuration, not a device name to hard-code as the architectural contract.

Before opening the resolved UART, the transport/bridge layer must perform startup ownership checks and fail clearly if the device is claimed by either the kernel serial console or a `serial-getty` service.

Conceptual flow:

`BWM semantic message -> UART transport adapter -> resolve DT uart0 alias -> validate device ownership -> open resolved /dev/tty* -> GPIO14/15`

Device-tree resolution and UART ownership checks belong exclusively to the UART transport/bridge layer. MQTT/common semantic events and translation runtime logic remain independent of Linux UART device names and of whether a semantic message crosses UART or IP networking. Message IDs/origin metadata remain the planned deduplication mechanism if redundant transports are enabled.

Generation-time safety is configuration-connected but disabled for the Stage 1 release baseline. Meaningful safety enforcement belongs to the later dynamic-runtime stage.

## Future multilingual ASR and River Culture retrieval

This is architecture guidance only; it does not change detector, capture,
playback, actuation, or runtime behaviour. The English River Culture corpus can
be searched through either of two independently configurable routes:

`captured utterance -> ASR translate_to_english -> English query -> English embedding backend -> English corpus retrieval`

or:

`captured utterance -> ASR transcribe -> native-language query -> multilingual embedding backend -> English corpus retrieval`

Neither route is mandatory. The selection must be based primarily on whether
the recognized query retrieves an intended or semantically appropriate English
source region from the same captured whispered utterance; ASR transcription
accuracy alone is not the decision metric. Latency, Pi resource use, model size,
operational simplicity, inspectability, and uncertainty in language detection
are secondary evaluation criteria.

Initial languages are English, German, and Italian. Brazilian Portuguese,
Dutch, and Austrian German are future-compatible additions. Austrian German is
a German language variant, not a separate pipeline branch. Do not introduce
per-language pipeline branches unless future backend evidence requires them.
Future configuration should expose an ASR output mode (`transcribe` or
`translate_to_english`) independently from an embedding backend (`multilingual`
or `english`).

For fair future comparison, retain each captured audio source and capture
identity alongside language, ground-truth transcription where available,
speaker/session identity, native ASR transcript, ASR English translation,
retrieval route, ranked passage/chunk IDs and scores, and intended/acceptable
retrieval outcome. Producing text must never discard the original captured
audio. This requirement does not alter Stage 3P capture behaviour.
