# Stage 3Q extension: Pi CPU ASR worker and benchmark

`live.asr_worker.PersistentASRWorker` owns a single separate process, loading
Faster-Whisper once and accepting one pending completed capture. It defaults to
`base` / CPU / `int8` / two threads / niceness 10; `small` remains the offline
quality reference and `tiny` is the fallback candidate. The worker is only
given completed `AudioSegment` objects, so detector, ReSpeaker, capture,
actuation, and UART timing do not wait on ASR.

The worker returns backend-neutral structured results through `poll()`, with
the submitted capture metadata preserved. A future live runner can hand it a
completed capture and consume that result without importing Faster-Whisper
internals. Stage 3Q intentionally does not implement detector/capture, UART,
actuation, retrieval, or display integration.

On the Pi, after installing the optional ASR requirement and prefetching the
models, run a realistic-load comparison (do not interpret laptop latency):

```bash
cd /home/raspi/BWM/translation
GPIOZERO_PIN_FACTORY=mock ../translation/whisper_venv/bin/python tools/benchmark_asr_pi.py \
  --wav test_files/test_wavs/2_whisper.wav \
  --annotations test_files/test_wavs/annotations/2_whisper.csv \
  --models base tiny small --threads 1 2 3 4
```

Each non-overwriting CSV records model, threads, transcript/quality metrics,
audio and inference durations/RTF, process RSS, available RAM, swap, CPU,
temperature, and Pi throttling flags where supported. Run it alongside the
normal BWM stack and then select a candidate based on useful semantic recovery,
end-to-end responsiveness, and continuous detector health—not isolated laptop
timing or WER alone.
