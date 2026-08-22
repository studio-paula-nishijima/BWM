# Stage 3T live capture to ASR smoke test

On the Raspberry Pi, run from `translation/` with Faster-Whisper installed:

```sh
GPIOZERO_PIN_FACTORY=native python voice_rack_test_v0_7.py --no-actuation
```

The default is Faster-Whisper `base`, CPU `int8`, two threads, automatic
language detection, four seconds pre-roll, and a twelve-second maximum capture.
The live capture deliberately does not apply the old 1.5-second
detector-derived endpoint; maximum duration is the reliable completion path.

For a low-cost model check, change only the model:

```sh
GPIOZERO_PIN_FACTORY=native python voice_rack_test_v0_7.py --asr-model tiny --no-actuation
```

Useful test variants are `--no-live-asr` (capture without model work) and
`--diagnostic-console` (restores per-frame detector telemetry).  For standalone
Stage 3T cycling only, `--release-after-asr` explicitly releases the current
interaction after ASR; production remains busy until a later response/display
stage calls the transport-independent `complete_interaction()` seam. WAV mode and
explicit live CSV logging retain the existing analysis workflow.

Check that normal output reports `listening`, a whisper trigger, capture start
and completion, ASR ready/submitted/processing, detected language, and raw
transcript.  During inference, continue speaking or observe the detector: its
frames and any independent servo actuation must continue.  Repeat an
interaction, then inspect CPU, RAM, temperature, and throttling with the
normal Pi tools.  No MQTT, retrieval, Translation-Pi control, UART change, or
screen-state UI is involved in this stage.
