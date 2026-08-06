# Stage 3J labelled WAV analysis

Annotations are CSV interval records using these required columns:

```csv
wav_file,start_seconds,end_seconds,label
silent_whisper.wav,0.0,1.2,silence
silent_whisper.wav,1.2,2.4,whisper
```

Optional columns are `confidence`, `strength`, `speaker`, `distance`,
`noise_type`, and `notes`. Labels are exactly `silence`, `background_noise`,
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

The application logs a wall-clock `timestamp`; it is deliberately not used as
audio time. The tool prefers an explicit elapsed-time column and otherwise
derives time as `frame * 0.03` because WAV processing uses 480 samples at
16 kHz. It writes `labelled_frames.csv`, `feature_summary.csv`,
`feature_separation.csv`, and `evaluation_summary.csv` without changing
source logs or annotations.
