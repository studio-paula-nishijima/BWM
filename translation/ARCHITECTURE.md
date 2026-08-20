# Translation architecture

Implemented runtime path:

`events.npy -> activation/session controller -> fresh random segment / prepare_events() -> PlaybackEngine -> RuntimeModulationEngine -> RuntimeSafety -> EventRouter -> GPIOBackend`

`events.npy` is an immutable base score. The persistent service only reads it;
every activation prepares a private, freshly selected configured segment and
never regenerates or rewrites the score. Hardware topology is loaded from
`configs/hardware.yaml`; its six current solenoids are not an architectural
channel-count limit.

`PlaybackSessionRuntime` keeps the process and GPIO17 listener alive while
idle. Activation creates a new score/session; deactivation is explicit
cancellation, not a playback pause. A session uses wall-clock lifetime
(`playback.session_timeout_seconds`, currently 600 seconds) independently of
PlaybackEngine logical score time. Pause-and-fill freezes logical progression
only, never extends the session timeout. Timeout or cancellation clears all
delayed modulation events and strategy state, releases a reaction pause, stops
the score, and returns to low-resource idle.

PlaybackEngine decides when a base event is due. The modulation engine copies
it and maps it to zero, one, or many runtime events without mutating prepared
base events. It supports pass-through, suppression, replacement, delayed
overlay/insertion, override while base time continues, and pause-and-fill.
Cascades and multi-taps are configuration-driven named strategies rather than
architectural primitives. Delayed artistic outputs use an injected-clock queue
owned by modulation; this is not safety scheduling. RuntimeSafety sees every
hardware-bound event, including delayed modulation events. It observes
per-target request/accept/reject counts, durations, recent rate and rolling
duty using monotonic runtime time, never logical score time. Its deliberately
permissive emergency guards are not normal-operation tuning; base, cascade and
multi-tap behaviour should pass unchanged. Physical history persists across
sessions because the hardware remains live.

RuntimeSafety also retains a separate per-target, dimensionless thermal-load
heuristic. Accepted pulse time adds normalized load while real monotonic time
decays it with a configured first-order cooling constant. It is available for
observation by default and has an optional deliberately permissive emergency
cutoff. This is not a calibrated or validated coil-temperature predictor, nor
is its threshold a certified hardware temperature limit.

GPIO17 remains the local installation activation adapter. It calls the same
transport-independent controller surface that a future MQTT adapter may use:

`GPIO17 or future semantic input -> PlaybackSessionRuntime -> PlaybackEngine -> RuntimeModulationEngine -> RuntimeSafety -> EventRouter -> hardware`

`button_service.py` remains superseded legacy GPIO17-to-systemd infrastructure.
No service files are changed here. RuntimeSafety is the sole safety insertion
point downstream of modulation, and never contains strategy-specific logic.

Runtime reaction path:

`runtime trigger/category -> ReactionPolicy -> RuntimeModulationEngine -> RuntimeSafety`

ReactionPolicy selects configured strategies but never schedules autonomous
reactions or bypasses safety.

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
