# Voice / Whisper runtime architecture

This is the canonical architecture reference for the implemented live Voice
runtime.  It describes stable ownership boundaries and runtime contracts, not
detector research or River Culture ranking internals.  See `ARCHITECTURE.md`
for the Translation-side reaction boundary, `shared/messaging/README.md` for
the shared envelope, and the specialist READMEs in `tools/` for operational
and analysis procedures.

## Runtime path and ownership

`voice_rack_test_v0_7.py` is the current live composition root.  It keeps the
existing audio/detector pipeline running, feeds the `AudioRingBuffer`, and
passes only a real emitted (post-cooldown) whisper trigger to Voice.  Servo
actuation remains a parallel existing consumer of that emitted trigger; Voice
does not change detector or actuation policy.

For an admitted interaction the path is:

```text
audio/detector pipeline -> emitted whisper trigger -> Voice admission
-> conservative capture -> persistent ASR process -> structured ASR result
-> retrieval adapter -> opaque response text -> Oracle display
-> display completion -> complete_interaction() -> listening
```

`LiveASRCoordinator` in `src/live/voice_runtime.py` owns admission, capture
submission, ASR-result collection, and the authoritative `VoiceLifecycle`.
`PersistentASRWorker` in `src/live/asr_worker.py` owns one lower-priority
Faster-Whisper child process and a bounded request queue.  `OracleInteractionController`
in `src/live/interaction.py` owns a separate, single-worker retrieval executor
and display scheduling.  It must not change Voice admission or ASR ownership.

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

The integrated runtime and its visible Oracle display are enabled by default.
`--no-oracle` is the explicit capture/ASR-only opt-out; `--oracle` remains a
compatible explicit opt-in spelling. `--oracle-headless` selects the headless
controller; `--oracle-width`, `--oracle-height`, `--oracle-fullscreen`, and
`--oracle-response-seconds` control presentation. `display.poll()` emits
completion only after the static/scroll presentation duration, and that event
is what calls `complete_interaction()`.

## Shared Voice-state messaging

Voice uses the repo-wide `shared/messaging/` implementation; it does not own a
second MQTT stack.  With `--voice-mqtt`, `VoiceStatePublisher` observes genuine
lifecycle transitions and publishes one shared envelope per transition:

```text
topic: bwm/voice/state
type:  voice.state
payload: {"state": "<VoiceState>"}
```

The shared envelope supplies IDs, origin, timestamp, version, QoS, and
reconnection conventions.  Same-state assignments publish nothing.  MQTT
publication failure is logged but cannot alter or corrupt the local lifecycle.
Voice publishes semantic state only: it neither selects Translation reactions
nor sends solenoid, GPIO, or modulation instructions.

When UART is configured, this existing authoritative lifecycle observer still
builds one `voice.state` envelope per genuine transition and fans the same ID
to MQTT and UART. UART transport failure is isolated degradation and cannot
change lifecycle timing or busy admission; display completion remains release.

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

The integrated Pi smoke test is documented in `tools/README_stage3u_oracle.md`.
`tools/README_stage3t_live_asr.md` covers the capture/ASR operational path,
while detector variants and offline evaluation remain documented by their
existing specialist tooling rather than here.
