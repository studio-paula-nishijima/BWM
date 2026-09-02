# Stage 3U Oracle smoke test

Run from `translation/` on the Pi after installing the base translation
requirements plus the River Culture retrieval requirements and building a
selected retrieval index:

```sh
GPIOZERO_PIN_FACTORY=native python whisper_runtime.py --oracle-width 800 --oracle-height 480 --no-actuation --voice-mqtt
```

The Oracle display/integration is enabled by default. Start windowed first; add
`--oracle-fullscreen` for installation deployment. Use `--no-oracle` only for
capture/ASR-only runs.
Use `--oracle-headless` to exercise ASR, retrieval and completion without SDL,
and omit `--voice-mqtt` for standalone broker-free operation.

## Stage V Voice-state demonstrator

Voice starts automatically through `idle -> initializing -> listening`; it
does not consume installation activation and has no implemented quiescence
state. It remains locally operable without Translation, MQTT, UART, or the
person detector. The shared UART transport publishes the same lifecycle event
by default. `--voice-mqtt` additionally enables MQTT publication. Use
`--no-voice-uart` only for an MQTT-only or standalone run; `--voice-uart`
remains an explicit compatible spelling. Translation's shared UART ingress is
also enabled by default and failure-isolated: an unavailable UART is logged
while normal playback continues. It resolves DT `uart0` at runtime and never
selects `/dev/serial0`.

This default is operational convenience, not an architectural dependency:
UART-only, MQTT-only, and MQTT-plus-UART deployments use the same semantic
event and Translation reaction path. With both transports selected, one event
ID is delivered redundantly and Translation reacts once after deduplication.
Transport selection does not control Voice lifecycle, and transport loss never
means inactive or quiescent.

Use either transport independently, or both:

```text
(no messaging flag)              # UART only, the default
--voice-mqtt                      # MQTT + UART
--voice-mqtt --no-voice-uart      # MQTT only
```

For each genuine lifecycle transition, Voice creates one `voice.state` event
and sends that unchanged envelope to every selected transport.  In particular,
the default `capture_processing` transition reaches Translation's semantic
ingress, where ID deduplication precedes the existing configured Voice
reaction.  A messaging failure is logged and never interrupts local capture,
ASR, retrieval, Oracle presentation, or display-completion release.

Demo responsiveness controls: `configs/asr.yaml` sets a 10-second inference
timeout; a timed-out worker is recycled and follows the retrieval-owned
fallback path. Response presentation is capped at 8 seconds without changing
the response text. `configs/servos.yaml` sets a 3-second delay from admitted
capture start; busy detector triggers do not schedule a servo action.

Verify the startup “The Oracle stirs...” view before listening, then the whisper
and considering views, raw ASR transcript,
retrieval query/result, and that the exact result text reaches the Oracle
response view. A static response remains for `--oracle-response-seconds`;
longer text scrolls. Detector triggers during the response must report busy.
After `[Display] response complete`, Voice returns to listening and accepts the
next interaction. With MQTT enabled, inspect `bwm/voice/state` for one shared
`voice.state` envelope per actual lifecycle transition. Observe CPU, RAM,
temperature and throttling with the normal Pi tools during a live interaction.
For an empty transcript or a recoverable retrieval failure, confirm concise
`[ASR]`/`[Retrieval] ERROR` diagnostics identify the reason while the visitor
still receives the retrieval-configured River Culture fallback response.
