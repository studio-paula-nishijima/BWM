# Stage 3U Oracle smoke test

Run from `translation/` on the Pi after installing the base translation
requirements plus the River Culture retrieval requirements and building a
selected retrieval index:

```sh
GPIOZERO_PIN_FACTORY=native python voice_rack_test_v0_7.py --oracle --oracle-width 800 --oracle-height 480 --no-actuation --voice-mqtt
```

Start windowed first; add `--oracle-fullscreen` for installation deployment.
Use `--oracle-headless` to exercise ASR, retrieval and completion without SDL,
and omit `--voice-mqtt` for standalone broker-free operation.

Verify the listening view, whisper and considering views, raw ASR transcript,
retrieval query/result, and that the exact result text reaches the Oracle
response view. A static response remains for `--oracle-response-seconds`;
longer text scrolls. Detector triggers during the response must report busy.
After `[Display] response complete`, Voice returns to listening and accepts the
next interaction. With MQTT enabled, inspect `bwm/voice/state` for one shared
`voice.state` envelope per actual lifecycle transition. Observe CPU, RAM,
temperature and throttling with the normal Pi tools during a live interaction.
