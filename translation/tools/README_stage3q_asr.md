# Stage 3Q offline whispered-ASR evaluation

Stage 3Q adds a file-only ASR evaluation path. It does not initialise audio or
hardware, and does not alter detector, capture, trigger, actuation, acquisition,
or annotation behaviour.

The baseline is [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper),
default model `small`, selected for multilingual English/German/Italian
transcription and Whisper's direct-English `translate` task. Install the
optional evaluation dependency with `pip install -r requirements/requirements_asr.txt`.
Model weights download on first actual run, never during tests. This is intended
initially for a capable workstation; `small` is not a real-time Raspberry Pi 5
deployment commitment. The adapter keeps model/device/compute type configurable
for later Pi candidates.

```powershell
python -m src.analysis.evaluate_asr --input-mode whole_wav --wav test_files/test_wavs/2_whisper.wav --output-tag whole
python -m src.analysis.evaluate_asr --input-mode annotated_span --wav test.wav --annotations annotations/test.csv --language en
python -m src.analysis.evaluate_asr --input-mode captured_clip --capture-output analysis_output/3P --capture-metadata captures.csv
```

`asr_*/asr_utterances.csv` retains raw and normalized text, language metadata,
segments/raw backend payloads, WER edit counts, exact match, word recall, and
timing. `asr_whole_wav.csv` preserves full-file results separately and
`asr_summary.csv` groups by input mode, language, detector profile, and output
mode. Output directories are tagged and never overwritten.

Metric normalization is Unicode NFKC, lower-case, punctuation-to-space, and
whitespace collapse. It deliberately does not stem, translate, or otherwise
rewrite words. Whole-WAV transcripts are never misleadingly scored against an
individual annotation when a WAV contains multiple utterances.
