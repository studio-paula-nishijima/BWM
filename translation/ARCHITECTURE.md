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

## Session teardown and hardware quiescence

Every timeout, explicit GPIO17/MQTT cancellation, and completed score uses one
authoritative session teardown path:

`ACTIVE SESSION -> close session admission -> clear RuntimeModulation -> stop PlaybackEngine -> quiesce GPIOBackend -> IDLE`

Entering IDLE guarantees that no actuation from the ended session remains
queued and every configured actuator output has been explicitly driven OFF.
`GPIOBackend.quiesce()` blocks pulse admission, invalidates and drains queued
work, lets a pulse already physically ON finish, then verifies all outputs OFF.
Its generation guard prevents a pulse dequeued immediately before cancellation
from starting after teardown; it does not release GPIO ownership or terminate
workers. A later activation reopens the reusable backend and prepares an
entirely fresh playback/modulation session.

Full process shutdown is different: it quiesces first, then stops workers and
closes GPIO devices. The persistent source score, GPIO17 listener, MQTT
connection, backend ownership, and RuntimeSafety physical/thermal history live
across normal session boundaries. Playback state, modulation state, and queued
backend work do not. Concise `[Session]`, `[GPIOBackend]`, and `[MQTT]` console
messages record activation, teardown reason, queue quiescence, and semantic
activation handling without polling or per-loop output.

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

`person detector -> shared semantic MQTT activation -> TranslationMQTTAdapter -> PlaybackSessionRuntime -> PlaybackEngine -> RuntimeModulationEngine -> RuntimeSafety -> EventRouter -> hardware`

`GPIO17 -> LocalActivationInput -> same PlaybackSessionRuntime -> PlaybackEngine -> RuntimeModulationEngine -> RuntimeSafety -> EventRouter -> hardware`

Stage 6 implements the repo-wide `shared.messaging` envelope and MQTT wrapper;
it is not owned by Translation. MQTT `installation.activation` is explicit
`active`/`inactive` state on a semantic topic. A bounded shared ID cache
suppresses delivery duplicates. A new-ID `active` while a session is active is
also a no-op: it neither starts a new segment nor resets the configured
600-second wall-clock session. `inactive` cancels through the same session
path. A later activation creates a fresh segment.

MQTT is optional (`configs/mqtt.yaml`) and non-retained at QoS 1. Its paho
network-loop thread reconnects with a bounded delay. A missing broker or a
disconnect never terminates the persistent process or disables the independent
GPIO17 fallback. GPIO17 may later publish shared installation state for other
subsystems, but Stage 6 intentionally does not make local activation depend on
that publication. UART and MQTT-to-UART bridging remain future work; the
repo-wide IDs and origins prepare for transport-independent deduplication.

`button_service.py` remains superseded legacy GPIO17-to-systemd infrastructure.
No service files are changed here. RuntimeSafety is the sole safety insertion
point downstream of modulation, and never contains strategy-specific logic.

Runtime reaction path:

`runtime trigger/category -> ReactionPolicy -> RuntimeModulationEngine -> RuntimeSafety`

ReactionPolicy selects configured strategies but never schedules autonomous
reactions or bypasses safety.

## Stage 7 Voice-state interaction

`Voice subsystem -> voice.state MQTT -> TranslationMQTTAdapter -> transition
matcher -> external-reaction busy guard -> ReactionPolicy ->
RuntimeModulationEngine -> RuntimeSafety -> EventRouter -> GPIOBackend`

The shared `voice.state` contract accepts `idle`, `listening`,
`whisper_detected`, `capture_processing`, and `response_displayed`. Translation
retains only the latest state for diagnostics. `voice_interaction.trigger_state`
is configurable and defaults to `capture_processing`; only a transition *into*
that state may trigger. Voice state never activates Translation or changes its
600-second wall-clock session.

The default `voice_default` policy selects configured cascade/multi-tap
reactions and uses overlay timeline policy, so the base score continues while
the reaction is busy. `PAUSE_AND_FILL` remains available as an explicit
strategy configuration. Translation owns reaction selection; Voice sends no
strategy, target, or GPIO instructions.

The initial Voice reaction policy is entirely YAML-configured and offers four
non-pausing reactions. `voice_simultaneous_then_sequence` temporarily overrides
base output: after a 0.5 s quiet gap measured from RuntimeSafety's latest
admitted actuation, it strikes every configured target together, waits 0.5 s,
then follows the configured target order at 0.2 s spacing and retains the
override for a final 1.0 s. `voice_cascade` uses the same 0.5 s quiet
gap, strikes its configured order at 0.3 s spacing, and retains a 1.0 s tail.
Both continue logical score time and intentionally drop base events due during
their override; normal routing resumes at the current score position.

`voice_triple_tap` and `voice_double_tap` are temporary non-pausing base-event
transformations. For their configurable 3.0 s and 4.0 s windows respectively,
each due base event becomes three or two taps on that event's own target, at
0.2 s spacing. After the window, ordinary pass-through resumes. All timing,
target order, target set, pulse seed, choices, and weights are configuration,
not a fixed actuator topology. None of these initial reactions uses
`PAUSE_AND_FILL`; that timeline policy remains opt-in for a future reaction.

The editable reaction definitions and Voice policy are in
`configs/voice_reactions.yaml`; `configs/runtime.yaml` retains base playback,
modulation, safety, and session settings. Override
reactions use a short phase list (`simultaneous`, `sequence`, `wait`); a phase
may use `targets: all`, which resolves to every configured hardware target at
startup, or an explicit ordered target list. Repeat transforms use
`duration_seconds`, `repeat_count`, and `tap_spacing_seconds`. Add or alter a
reaction by editing those fields and the `voice_default` policy choices; set
that policy to `fixed` with a selected strategy to tune one reaction. Invalid
types, phases, targets, timings, repeat counts, or policy references fail
clearly at startup before hardware work is admitted.

An accepted external reaction is busy until its final delayed output has been
emitted (and any pause-and-fill resumes). Matching transitions while busy are
dropped, never queued. Session timeout, cancellation, and teardown clear
modulation and busy state before GPIO quiescence, so a late MQTT callback
cannot admit work. MQTT duplicate-ID filtering occurs before transition logic;
new IDs reporting the same state update observation but do not retrigger.

For a Pi smoke test, activate Translation then run:
`python translation/tools/simulate_voice_state.py listening`,
`python translation/tools/simulate_voice_state.py capture_processing`, wait for
completion, publish a state away from the trigger, then publish
`capture_processing` again. A second trigger while busy is intentionally
ignored. Stage 8 transports must preserve envelope IDs/origins and route every
delivery through this same deduplication, transition, and busy logic.

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

## Voice/Whisper and River Culture retrieval

The implemented Voice runtime is documented canonically in
`VOICE_ARCHITECTURE.md`. It uses structured ASR output to call the existing
River Culture retrieval runtime and presents its opaque top response text in
the Oracle display. Voice remains responsible for its own admission and
lifecycle, including waiting for display completion before releasing an
interaction. Its optional shared `voice.state` publication is semantic only;
Translation's existing reaction path above remains Translation-owned.

The following are future multilingual retrieval alternatives, not a description
of the current integrated `transcribe` runtime. The English River Culture corpus
can be searched through either of two independently configurable routes:

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
