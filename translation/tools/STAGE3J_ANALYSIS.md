# Stage 3J labelled WAV analysis

Annotations are CSV interval records using these required columns:

```csv
wav_file,start_seconds,end_seconds,label
silent_whisper.wav,0.0,1.2,silence
silent_whisper.wav,1.2,2.4,whisper
```

Optional segment columns are `confidence`, `strength`, `speaker`, `distance`,
`noise_type`, and `notes`. Optional utterance metadata columns are
`utterance_id`, `language`, `transcription`, `speaker_id`, and `session_id`.
Use a stable BCP 47-style language tag such as `en`, `de`, or `it` where known.
Labels are exactly `silence`, `background_noise`,
`normal_speech`, `whisper`, and `uncertain`. Intervals are `[start, end)`;
shared boundaries belong to the later interval. `uncertain` is retained in the
derived frames but excluded from evaluation. Overlap warns by default and may
be rejected with `--reject-overlaps`. For a single-WAV annotation file used
through `--triplet`, `wav_file` may be omitted: the CLI adds the WAV filename
in memory only, leaving the original annotation file unchanged.

For one recording:

```sh
python tools/analyse_labelled_wavs.py --triplet test_files/test_wavs/silent_whisper.wav,logs/silent_whisper_analysis.csv,test_files/test_wavs/annotations/silent_whisper.csv --output-dir analysis_output
```

For multiple recordings, use a manifest containing `wav_file,log_file,annotation_file`:

```sh
python tools/analyse_labelled_wavs.py --manifest analysis_manifest.csv --output-dir analysis_output --weighting segment
streamlit run src/viz/labelled_wav_app.py
```

Pass `--analysis-tag 3L_webrtc` to append that tag to every export filename,
for example `labelled_frames_3L_webrtc.csv` and
`evaluation_summary_3L_webrtc.csv`. Without a tag, the existing filenames are
unchanged.

The application logs a wall-clock `timestamp`; it is deliberately not used as
audio time. The tool prefers an explicit elapsed-time column and otherwise
derives time as `frame * 0.03` because WAV processing uses 480 samples at
16 kHz. It writes `labelled_frames.csv`, `feature_summary.csv`,
`feature_separation.csv`, `evaluation_summary.csv`, and
`qualifying_run_summary.csv` without changing source logs or annotations.

For upcoming utterance/STT work, annotate a complete whispered question as one
`whisper` interval where possible and record its `utterance_id`, language,
ground-truth transcription, and anonymous speaker/session IDs when known.  An
utterance may span multiple annotation rows (for example an internal pause)
when those rows share an `utterance_id`.  Do not add word timestamps unless a
later analysis needs them.  Existing three/four-column files remain valid.

The labelled-frame export carries the compact `utterance_id`, `language`,
`speaker_id`, and `session_id` fields as `annotation_*` columns.  To avoid
repeating long transcriptions on every frame, each analysis run also writes
`utterance_metadata.csv` (or `utterance_metadata_<tag>.csv`) with one row per
identified utterance and its complete transcription and annotation span.  A
metadata-bearing segment without an `utterance_id` is also retained as its own
row with a blank ID; the analysis never invents or infers an ID.

## Analysis-only context sweep

`tools/analyse_normal_speech_context_sweep.py` replays policies from an
existing labelled-frame export; it never loads WAV audio or affects live
detection.  The Stage 3Q sweep uses temporal-v1 candidate evidence, recent
Silero speech-probability context, and confirmation penalties only (no veto):

```sh
python tools/analyse_normal_speech_context_sweep.py \
  --labelled-frames analysis_output/3P/labelled_frames_3P.csv \
  --output-dir analysis_output/3Q_context_sweep \
  --analysis-tag 3Q_context_sweep
```

It evaluates 0.6/1.0/1.5-second lookback windows, high-Silero fractions of
0.1/0.2/0.3 (`speech_probability >= 0.5`), and confirmation penalties of
24/30/36 frames.  Candidate state is continuous within each WAV; an additional
segment-local calculation exposes annotation-boundary continuations.
