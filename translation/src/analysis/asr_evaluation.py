"""Offline ASR evaluation for annotated WAVs and Stage 3P capture exports.

This module is deliberately independent of live detector, capture, actuation,
and acquisition code.  Backends receive decoded audio segments and return a
small backend-neutral result, making model downloads unnecessary for tests.
"""
from __future__ import annotations

import csv
import json
import math
import re
import time
import unicodedata
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

from .labelled_wav import load_annotations, utterance_metadata_summary

INPUT_MODES = ("annotated_span", "whole_wav", "captured_clip")
OUTPUT_MODES = ("transcribe", "translate_to_english")
# Canonical annotation metadata is intentionally human-readable. Faster-Whisper
# instead requires its short language codes; retain the annotation value in
# outputs and translate only at the adapter boundary.
LANGUAGE_ALIASES = {
    "en": "en", "english": "en", "de": "de", "german": "de", "deutsch": "de",
    "it": "it", "italian": "it", "italiano": "it", "pt": "pt",
    "portuguese": "pt", "brazilian portuguese": "pt", "brazilian-portuguese": "pt",
    "pt-br": "pt", "nl": "nl", "dutch": "nl",
}


@dataclass(frozen=True)
class AudioSegment:
    samples: np.ndarray
    sample_rate: int
    source_wav: str
    start_seconds: float = 0.0
    end_seconds: float | None = None

    @property
    def duration_seconds(self):
        return len(self.samples) / float(self.sample_rate)


@dataclass
class ASRResult:
    recognized_text: str = ""
    detected_language: str | None = None
    language_confidence: float | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class ASRBackend(Protocol):
    name: str
    model: str

    def transcribe(self, audio: AudioSegment, *, output_mode: str,
                   language: str | None = None) -> ASRResult: ...


class FasterWhisperBackend:
    """Lazy Faster-Whisper adapter; import/model creation occur only on use."""
    name = "faster_whisper"

    def __init__(self, model="small", device="auto", compute_type="auto", cpu_threads=0):
        self.model = model
        self._device, self._compute_type, self._cpu_threads, self._instance = device, compute_type, cpu_threads, None

    def _load(self):
        if self._instance is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("Faster-Whisper is not installed. Install requirements/requirements_asr.txt.") from exc
            options = {"device": self._device, "compute_type": self._compute_type}
            if self._cpu_threads:
                options["cpu_threads"] = self._cpu_threads
            self._instance = WhisperModel(self.model, **options)
        return self._instance

    def transcribe(self, audio, *, output_mode, language=None):
        if output_mode not in OUTPUT_MODES:
            raise ValueError(f"Unsupported ASR output mode: {output_mode}")
        segments, info = self._load().transcribe(
            audio.samples, language=language, task="translate" if output_mode == "translate_to_english" else "transcribe",
            word_timestamps=True,
        )
        output = []
        for segment in segments:
            output.append({"start": segment.start, "end": segment.end, "text": segment.text,
                           "avg_logprob": getattr(segment, "avg_logprob", None),
                           "no_speech_prob": getattr(segment, "no_speech_prob", None),
                           "words": [asdict(word) for word in (getattr(segment, "words", None) or [])]})
        return ASRResult("".join(item["text"] for item in output).strip(), getattr(info, "language", None),
                         getattr(info, "language_probability", None), output,
                         {"duration_after_vad": getattr(info, "duration_after_vad", None)})


def normalize_text(text: str | None) -> str:
    """NFKC, lowercase, punctuation-to-space, then collapse whitespace."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = "".join(" " if unicodedata.category(char).startswith("P") else char for char in text)
    return " ".join(text.split())


def resolve_asr_language(language: str | None) -> str | None:
    """Map readable annotation language names to Faster-Whisper language codes.

    Unknown non-empty values pass through unchanged so the backend can report a
    clear unsupported-code error rather than silently changing annotation data.
    """
    if language is None or pd.isna(language) or not str(language).strip():
        return None
    value = str(language).strip().lower().replace("_", "-")
    return LANGUAGE_ALIASES.get(value, value)


def word_error_counts(reference: str, hypothesis: str) -> dict[str, int | float]:
    ref, hyp = normalize_text(reference).split(), normalize_text(hypothesis).split()
    matrix = [[(0, 0, 0, 0) for _ in range(len(hyp) + 1)] for _ in range(len(ref) + 1)]
    for i in range(1, len(ref) + 1): matrix[i][0] = (i, 0, i, 0)
    for j in range(1, len(hyp) + 1): matrix[0][j] = (j, 0, 0, j)
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            if ref[i - 1] == hyp[j - 1]:
                matrix[i][j] = matrix[i - 1][j - 1]
            else:
                candidates = [(matrix[i - 1][j][0] + 1, matrix[i - 1][j][1], matrix[i - 1][j][2] + 1, matrix[i - 1][j][3]),
                              (matrix[i][j - 1][0] + 1, matrix[i][j - 1][1], matrix[i][j - 1][2], matrix[i][j - 1][3] + 1),
                              (matrix[i - 1][j - 1][0] + 1, matrix[i - 1][j - 1][1] + 1, matrix[i - 1][j - 1][2], matrix[i - 1][j - 1][3])]
                matrix[i][j] = min(candidates, key=lambda item: item[0])
    errors, substitutions, deletions, insertions = matrix[-1][-1]
    correct = len(ref) - substitutions - deletions
    return {"word_count": len(ref), "correct_words": correct, "substitutions": substitutions,
            "deletions": deletions, "insertions": insertions,
            "wer": errors / len(ref) if ref else math.nan,
            "word_recall": correct / len(ref) if ref else math.nan,
            "exact_match": normalize_text(reference) == normalize_text(hypothesis)}


def read_wav(path: str | Path) -> AudioSegment:
    path = Path(path)
    with wave.open(str(path), "rb") as handle:
        channels, width, rate, frames = handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.getnframes()
        raw = handle.readframes(frames)
    if width == 1: samples = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif width == 2: samples = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif width == 3:
        values = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        samples = (values[:, 0].astype(np.int32) | (values[:, 1].astype(np.int32) << 8) | (values[:, 2].astype(np.int32) << 16))
        samples = ((samples ^ (1 << 23)) - (1 << 23)).astype(np.float32) / (1 << 23)
    elif width == 4: samples = np.frombuffer(raw, "<i4").astype(np.float32) / (1 << 31)
    else: raise ValueError(f"Unsupported WAV sample width: {width}")
    if channels > 1: samples = samples.reshape(-1, channels).mean(axis=1)
    return AudioSegment(samples, rate, str(path), 0.0, frames / float(rate))


def crop_audio(audio: AudioSegment, start_seconds: float, end_seconds: float) -> AudioSegment:
    start = max(0, int(math.floor(start_seconds * audio.sample_rate)))
    end = min(len(audio.samples), int(math.ceil(end_seconds * audio.sample_rate)))
    if end <= start: raise ValueError("Annotated audio span is empty after sample-boundary conversion")
    return AudioSegment(audio.samples[start:end], audio.sample_rate, audio.source_wav,
                        start / audio.sample_rate, end / audio.sample_rate)


def _empty(value): return value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value)


def annotation_items(wav_path, annotation_path):
    annotations = load_annotations(annotation_path, wav_root=Path(wav_path).parent, default_wav_file=Path(wav_path).name)
    return utterance_metadata_summary(annotations).to_dict("records")


def discover_capture_items(capture_output, metadata_path=None):
    root = Path(capture_output)
    paths = [Path(metadata_path)] if metadata_path else sorted(root.rglob("*.csv"))
    aliases = ("capture_wav", "captured_wav", "capture_path", "captured_clip", "wav_path", "output_wav")
    for path in paths:
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, UnicodeDecodeError): continue
        if not rows or not set(rows[0]).intersection(aliases): continue
        result = []
        for index, row in enumerate(rows):
            value = next((row.get(name) for name in aliases if row.get(name)), None)
            if not value: continue
            wav = Path(value); wav = wav if wav.is_absolute() else (path.parent / wav)
            result.append({"capture_wav": str(wav), "capture_id": row.get("capture_id") or row.get("capture_index") or str(index),
                           "source_wav": row.get("source_wav") or row.get("wav_file"), "utterance_id": row.get("utterance_id") or row.get("matched_utterance_id"),
                           "detector_profile": row.get("detector_profile"), "capture_policy": row.get("capture_policy"),
                           "completion_reason": row.get("completion_reason"), "language": row.get("language"),
                           "speaker_id": row.get("speaker_id"), "session_id": row.get("session_id"),
                           "ground_truth_transcription": row.get("transcription")})
        return result
    raise ValueError("No capture metadata CSV with a supported capture WAV column was found")


def _row(audio, item, input_mode, backend, output_mode, asr_language, language_handling):
    started = time.perf_counter()
    try:
        result, status, error = backend.transcribe(audio, output_mode=output_mode, language=asr_language), "ok", ""
    except Exception as exc: result, status, error = ASRResult(), "inference_failed", f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    reference = item.get("transcription") or item.get("ground_truth_transcription") or ""
    metrics = word_error_counts(reference, result.recognized_text) if reference else {
        "word_count": math.nan, "correct_words": math.nan, "substitutions": math.nan,
        "deletions": math.nan, "insertions": math.nan, "wer": math.nan,
        "word_recall": math.nan, "exact_match": math.nan,
    }
    return {"source_wav": item.get("wav_file") or item.get("source_wav") or audio.source_wav, "utterance_id": item.get("utterance_id"),
            "capture_id": item.get("capture_id"), "input_mode": input_mode, "language": item.get("language"),
            "asr_language_requested": asr_language, "language_handling": language_handling, "speaker_id": item.get("speaker_id"), "session_id": item.get("session_id"),
            "detector_profile": item.get("detector_profile"), "capture_policy": item.get("capture_policy"), "completion_reason": item.get("completion_reason"),
            "ground_truth_transcription": reference, "asr_backend": backend.name, "asr_model": backend.model,
            "asr_output_mode": output_mode, "recognized_text_raw": result.recognized_text, "recognized_text_normalized": normalize_text(result.recognized_text),
            "detected_language": result.detected_language, "language_confidence": result.language_confidence,
            "segments_json": json.dumps(result.segments, ensure_ascii=False), "raw_backend_json": json.dumps(result.raw, ensure_ascii=False),
            "status": status, "error": error, "audio_duration": audio.duration_seconds, "inference_duration": elapsed,
            "real_time_factor": elapsed / audio.duration_seconds if audio.duration_seconds else math.nan, **metrics}


def evaluate(backend, *, input_mode, wav_path=None, annotation_path=None, capture_output=None,
             capture_metadata=None, output_mode="transcribe", language=None):
    if input_mode not in INPUT_MODES: raise ValueError(f"Unsupported input mode: {input_mode}")
    if output_mode not in OUTPUT_MODES: raise ValueError(f"Unsupported ASR output mode: {output_mode}")
    rows, whole_rows = [], []
    def language_request(item):
        requested = language if language is not None else item.get("language")
        return resolve_asr_language(requested), "supplied" if language is not None else ("annotation" if requested else "auto")
    if input_mode == "captured_clip":
        if not capture_output: raise ValueError("captured_clip mode requires capture_output")
        for item in discover_capture_items(capture_output, capture_metadata):
            audio = read_wav(item["capture_wav"])
            asr_language, handling = language_request(item)
            rows.append(_row(audio, item, input_mode, backend, output_mode, asr_language, handling))
    else:
        if not wav_path: raise ValueError(f"{input_mode} mode requires wav_path")
        audio = read_wav(wav_path)
        items = annotation_items(wav_path, annotation_path) if annotation_path else []
        if input_mode == "whole_wav":
            item = {"wav_file": Path(wav_path).name, "language": language}
            asr_language, handling = language_request(item)
            row = _row(audio, item, input_mode, backend, output_mode, asr_language, handling)
            whole_rows.append(row); rows.append(row)
            # Multiple annotations are intentionally not scored against a whole-file transcript.
        else:
            if not annotation_path: raise ValueError("annotated_span mode requires annotation_path")
            for item in items:
                clip = crop_audio(audio, float(item["start_seconds"]), float(item["end_seconds"]))
                asr_language, handling = language_request(item)
                rows.append(_row(clip, item, input_mode, backend, output_mode, asr_language, handling))
    return pd.DataFrame(rows), pd.DataFrame(whole_rows)


def write_outputs(rows, whole_rows, output_root, tag=None):
    root = Path(output_root); safe_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag or time.strftime("%Y%m%d_%H%M%S"))
    destination = root / f"asr_{safe_tag}"
    suffix = 1
    while destination.exists(): destination = root / f"asr_{safe_tag}_{suffix}"; suffix += 1
    destination.mkdir(parents=True)
    rows.to_csv(destination / "asr_utterances.csv", index=False)
    whole_rows.to_csv(destination / "asr_whole_wav.csv", index=False)
    groups = [name for name in ("input_mode", "language", "detector_profile", "asr_output_mode") if name in rows]
    summary = rows.groupby(groups, dropna=False).agg(utterances_evaluated=("status", "size"), mean_wer=("wer", "mean"), median_wer=("wer", "median"), mean_word_recall=("word_recall", "mean"), median_word_recall=("word_recall", "median"), exact_match_count=("exact_match", "sum"), empty_output_count=("recognized_text_raw", lambda s: int(s.fillna("").eq("").sum())), mean_inference_duration=("inference_duration", "mean"), mean_real_time_factor=("real_time_factor", "mean")).reset_index() if not rows.empty else pd.DataFrame()
    summary.to_csv(destination / "asr_summary.csv", index=False)
    return destination
