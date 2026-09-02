# Voice / Whisper runtime architecture

This is the canonical architecture reference for the implemented live Voice
runtime.  It describes stable ownership boundaries and runtime contracts, not
detector research or River Culture ranking internals.  See `ARCHITECTURE.md`
for the Translation-side reaction boundary, `shared/messaging/README.md` for
the shared envelope, and the specialist READMEs in `tools/` for operational
and analysis procedures.

## Runtime path and ownership

`whisper_runtime.py` is the stable production live composition root.  It keeps the
existing audio/detector pipeline running, feeds the `AudioRingBuffer`, and
passes only a real emitted (post-cooldown) whisper trigger to Voice.  Servo
actuation remains a parallel existing consumer of that emitted trigger; Voice
does not change detector or actuation policy.

## Interaction occurrence and artistic selector

At the existing detector-confirmation and cooldown seam, Voice emits one
`voice.interaction` event. Detector payloads carry `source: detector` and a
`silero_selection_value`: the median of the final ten qualifying Silero frames,
including the crossing frame, latched once. It is an artistic selector, not
loudness, calibrated confidence, or speaker identity. It chooses a configured
servo sequence 1–5. The backup button carries `source: button`, has no
fabricated value, and retains random servo selection.

For an admitted interaction the legacy Oracle demonstrator path is:

```text
audio/detector pipeline -> emitted whisper trigger -> Voice admission
-> conservative capture -> persistent ASR process -> structured ASR result
-> retrieval adapter -> opaque response text -> Oracle display
-> display completion -> complete_interaction() -> listening
```

The normal exhibition composition is detector + local servo + conservative
capture + persistent ASR.  It does not start Pygame, an Oracle display, or
River Culture retrieval resources.  `--oracle` selects the retained legacy
demonstrator path.  In exhibition mode each completed structured ASR result
(including timeout/error) releases the admitted interaction directly from
`capture_processing` to `listening`; it does not fabricate
`response_displayed`.

Servo feedback is scheduled directly at the real emitted detector trigger:
`profile_decision.trigger and now - last_trigger_time > COOLDOWN_SECONDS`,
immediately after `detector.record_trigger()` and timestamp update. It is not
coupled to capture admission, so a busy interaction still gets local feedback
but cannot start a second capture or ASR job. The 3.0-second configurable
delay begins at that emitted trigger and delayed work is cancelled on shutdown.

`LiveASRCoordinator` in `src/live/voice_runtime.py` owns admission, capture
submission, ASR-result collection, and the authoritative `VoiceLifecycle`.
`PersistentASRWorker` in `src/live/asr_worker.py` owns one lower-priority
Faster-Whisper child process and a bounded request queue.  `OracleInteractionController`
in `src/live/interaction.py` owns a separate, single-worker retrieval executor
and display scheduling.  It must not change Voice admission or ASR ownership.

## Independent autostart and future quiescence

Voice autostarts and operates according to its own configuration. It does not
wait for Translation to become active, an `installation.activation` event,
MQTT, UART, the person detector, or any other peer before the detector, servo
path, capture admission, ASR, and local runtime can operate. Translation and
Voice/Whisper are independent runtimes; peer absence or transport loss is
isolated degradation, never an implicit local `inactive` or quiescence state.

No Voice quiescence policy is implemented today. If one is added, it must
follow an explicit semantic instruction or explicit deployment policy, never
the absence of a message. It may block new interactions and deliberately
stop/restart heavy ASR or retrieval resources, while normally allowing an
already-admitted interaction to finish and preserving appropriate lightweight
local/hardware state. Explicit reactivation must restart cleanly. Translation
session timing does not create a separate Voice-side timer.

## Lifecycle and admission

The authoritative lifecycle is:

```text
idle -> initializing -> listening -> whisper_detected -> capture_processing
     -> response_displayed -> listening
```

The ordinary completed path starts at `listening`, progresses through the
three interaction states in order, and returns to `listening` only when
`complete_interaction()` is called after response presentation completes.
Repeated assignment of the same state is not a transition.

`initializing` covers required Voice resources loading and displays “The Oracle
stirs...”. An interaction is admitted only when the lifecycle is `listening` and capture
is not already active.  Once admitted, detector triggers remain observable and
may still drive their existing detector/servo handling, but they cannot start
another capture, ASR, retrieval, or display interaction.  This busy admission
guard is separate from detector cooldown: cooldown decides whether a detector
crossing is an emitted trigger; lifecycle admission decides whether that
emitted trigger starts an interaction.

ASR completion, retrieval completion, and the start of response display do
not release admission.  Display completion is the normal release boundary.
`--release-after-asr` is a standalone/debug cycling facility, not integrated
runtime behaviour.

## Capture and ASR result boundary

An accepted trigger uses the existing conservative capture controller: four
seconds of pre-roll and a fixed twelve-second maximum capture.  Audio-source
details remain upstream concerns.  The completed capture is submitted without
blocking the continuous detector loop to the persistent Faster-Whisper process.

The live default is Faster-Whisper `base`, CPU, `int8`, two CPU threads, and
automatic language detection.  ASR returns a structured result with capture
identity and timing metadata plus raw recognition fields, including
`recognized_text` and detected language where available.  Downstream code
consumes this result at the ASR-result boundary; it does not import or manage
the model worker.

The queue is intentionally bounded.  If ASR cannot accept a completed capture,
the result reports that status; Voice still remains busy until the integrated
response path completes or another explicit completion/error path closes it.

## Retrieval boundary and sequencing

After a successful ASR result with non-blank `recognized_text`, the interaction
controller submits retrieval asynchronously.  It does so after ASR result
collection rather than deliberately overlapping retrieval embedding inference
with active ASR inference.  Voice remains busy throughout both stages.

`src/live/retrieval_adapter.py` is the runtime interface to River Culture:

```text
textual ASR result -> RiverCultureRetrievalAdapter.retrieve(text)
                  -> {ok, response_text, metadata}
```

The adapter loads the configured existing retrieval entry point, keeps its
index/model lifetime outside Voice, and returns the top ranked source text as
`response_text`.  The Oracle integration treats that string as opaque and
passes it unchanged to the display.  Retrieval/ranking, source-region, and
quotation-selection changes belong behind this interface, not in Voice or the
display.  Current settings, model selection, index inputs, and `top_k` live in
`configs/river_culture_retrieval.json`; retrieval build/query detail is in
`tools/README_river_culture_retrieval.md`.

Blank ASR text and recoverable retrieval failures ask the retrieval adapter for
its configured River Culture fallback response. Voice/display never own visitor
fallback wording and always display returned text unchanged. Detailed error
reasons are emitted as `[ASR] ERROR`, `[Retrieval] ERROR`, or `[Display] failed`
diagnostics; a display failure also completes the interaction so local
admission cannot remain stuck.

## Oracle display

`src/live/oracle_display.py` defines the public command-oriented display
boundary.  `OracleDisplayController` is the deterministic headless controller
used by tests; `PygameOracleDisplayController` is the SDL/Pygame renderer.
Both support configured size, timing, wrapped static text, and scrolling long
responses.  Pygame supports windowed and fullscreen operation.

Lifecycle states map to visitor views as follows:

| Voice state | View text |
| --- | --- |
| `listening` | “The Oracle awaits your question. Whisper it to the water.” |
| `initializing` | “The Oracle stirs...” |
| `whisper_detected` | “The Oracle is listening to your question...” |
| `capture_processing` | “The Oracle is considering your question...” |
| `response_displayed` | “The Oracle responds”, followed by the retrieval response text |

The integrated runtime and its visible Oracle display are enabled by explicit
`--oracle` opt-in; the normal default is exhibition capture/ASR operation.
`--no-oracle` remains a compatible explicit spelling. `--oracle-headless` selects the headless
controller; `--oracle-width`, `--oracle-height`, `--oracle-fullscreen`, and
`--oracle-response-seconds` control presentation. `display.poll()` emits
completion only after the static/scroll presentation duration, and that event
is what calls `complete_interaction()`.

## Shared Voice-state messaging

## Voice active period and rpi02 interaction backup

Voice boots independently into normal operation and owns a local monotonic
active-period timer.  `configs/asr.yaml` supplies `voice_session` defaults:
600 seconds, active at boot, and a restartable ASR worker suspension policy.
The value intentionally aligns with Translation's installation duration, but
the timers do not share runtime ownership.  MQTT/UART loss, Translation
availability, detector availability, and BLE state never request quiescence.

Voice subscribes through `VoiceSemanticIngress` to shared
`installation.activation` envelopes on `bwm/installation/activation`.  An
`active` envelope resets the local timer; from quiescence it restarts Voice's
ASR worker and returns through `initializing` to `listening`.  `inactive` and
timer expiry use the same graceful path: new interaction admission closes,
an already admitted interaction completes normally, then the ASR child is
stopped.  Semantic ingress, process, and lightweight GPIO/control paths stay
alive so only an explicit `active` envelope can wake Voice.

rpi02's legacy voice-rack button wiring is GPIO17 to GND, internal pull-up,
falling-edge, 0.4-second debounce.  It is an interaction backup, never an
installation activation input (rpi03 GPIO17 remains Translation's independent
activation backup).  The Voice runner queues a valid button edge and handles
it at the same frame-boundary occurrence seam as an emitted detector trigger:
it schedules the existing delayed servo feedback and independently attempts
capture admission.  While busy it still schedules feedback but starts no
second capture; while quiescent it does neither and cannot wake Voice.

The legacy `button-controller-voice.service` must be disabled on rpi02 before
deployment because it separately claims GPIO17 to start/stop the old service.

Voice uses the repo-wide `shared/messaging/` implementation; it does not own a
second MQTT stack. UART Voice semantic publication is enabled by default in
the live runner. `--voice-mqtt` additionally enables MQTT publication;
`VoiceStatePublisher` observes genuine lifecycle transitions and builds one
shared envelope per transition:

```text
topic: bwm/voice/state
type:  voice.state
payload: {"state": "<VoiceState>"}
```

The shared envelope supplies IDs, origin, timestamp, version, QoS, and
reconnection conventions. Same-state assignments publish nothing. MQTT
publication failure is logged but cannot alter or corrupt the local lifecycle.
Voice publishes semantic state only: it neither selects Translation reactions
nor sends solenoid, GPIO, or modulation instructions. Transport selection
controls semantic publication only; it does not control Voice lifecycle.

When either or both transports are selected, this existing authoritative
lifecycle observer fans the same `voice.state` envelope, including its ID,
origin, timestamp, type, and payload, to each selected transport. UART and
MQTT failure are isolated degradation and cannot change lifecycle timing or
busy admission; display completion remains release.

UART is enabled by default for the deployed Stage V demonstrator, but that is
an operational default rather than a semantic dependency. The same Voice
event contract and Translation reaction path work with UART only, MQTT only,
or both transports. When both are selected, they carry the same envelope and
Translation deduplicates its ID before transition matching.

Translation currently reacts by default to a transition into
`capture_processing`, but transition matching, busy handling, reaction choice,
and actuation remain Translation-owned.  See `ARCHITECTURE.md` and
`shared/messaging/README.md`.

## Configuration, observability, and related tooling

`configs/asr.yaml` holds the live ASR defaults; `configs/whisper.yaml` holds
audio, selectable detector profiles, cooldown, and diagnostic-logging controls.
Temporal V2 profiles include a small rolling numerical-silence eligibility gate:
negligible band-pass RMS makes temporal/ZCR evidence ineligible, resets its
qualifying accumulation, and is not a speech or noise classifier. Production
retains the validated `silero_median_min: 0.0003`; all gate calibration remains
profile configuration.
Normal live output is concise and event/state-oriented: trigger/state changes,
capture/ASR status and raw result, retrieval response, and display completion.
High-volume detector telemetry is opt-in with `--diagnostic-console`; live CSV
logging and offline/analysis workflows remain supported through their existing
tools and READMEs.

For seven-month exhibition storage, successful non-empty transcripts are
appended best-effort to `logs/live_transcripts.csv` (configurable as
`asr.result_log_path`). The file has one CSV header and the minimal columns
`timestamp,capture_id,language,text`; Python's CSV writer preserves commas,
quotes, and embedded newlines in recognized text. Blank transcripts, timeouts,
and failed/error-only ASR results remain console diagnostics but are not
persisted. Logging failure is reported but cannot interrupt the Voice runtime.

The integrated Pi smoke test is documented in `tools/README_stage3u_oracle.md`.
`tools/README_stage3t_live_asr.md` covers the capture/ASR operational path,
while detector variants and offline evaluation remain documented by their
existing specialist tooling rather than here.
