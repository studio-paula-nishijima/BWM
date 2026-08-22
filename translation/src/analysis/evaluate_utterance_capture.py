"""Run the production detector and conservative capture controller on annotated WAVs.

This is intentionally offline-only: it creates no actuation controller and never
initialises PCA9685 hardware.  Detector/profile construction mirrors the Stage 3S
WAV path; annotations are used only after capture has completed.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ..audio.ring_buffer import AudioRingBuffer
from ..audio.utterance_capture import CapturePolicy, UtteranceCaptureController
from ..whisper.profiles import PROFILE_NAMES, TemporalProfilePolicy
from .labelled_wav import load_annotations


def utterance_envelopes(annotations):
    """Use existing utterance-ID grouping, with one whisper row as legacy fallback."""
    rows = []
    identified = annotations.loc[annotations.utterance_id.notna()]
    for (wav_file, utterance_id), group in identified.groupby(["wav_file", "utterance_id"], sort=False):
        rows.append(_envelope_row(wav_file, str(utterance_id), group, str(utterance_id)))
    # Older annotations commonly have one complete whisper per row and no ID.
    for row_index, row in annotations.loc[annotations.utterance_id.isna() & annotations.label.eq("whisper")].iterrows():
        rows.append(_envelope_row(row.wav_file, "", pd.DataFrame([row]), f"row_{row_index}"))
    return pd.DataFrame(rows, columns=["wav_file", "utterance_id", "effective_utterance_id", "ground_truth_start", "ground_truth_end", "language", "transcription", "speaker_id", "session_id"])


def _envelope_row(wav_file, utterance_id, group, effective_id):
    result = {"wav_file": wav_file, "utterance_id": utterance_id, "effective_utterance_id": effective_id,
              "ground_truth_start": float(group.start_seconds.min()), "ground_truth_end": float(group.end_seconds.max())}
    for column in ("language", "transcription", "speaker_id", "session_id"):
        values = group[column].dropna()
        result[column] = values.iloc[0] if not values.empty else ""
    return result


def match_captures(captures, utterances):
    """Transparent overlap matching: each capture selects its largest overlap."""
    capture_matches, utterance_matches = {}, {index: [] for index in utterances.index}
    for capture_index, capture in enumerate(captures):
        start, end = capture.time(capture.capture_start_sample), capture.time(capture.final_end_sample)
        overlaps = []
        for utterance_index, utterance in utterances.iterrows():
            amount = max(0.0, min(end, utterance.ground_truth_end) - max(start, utterance.ground_truth_start))
            if amount > 0:
                overlaps.append((amount, utterance_index))
                utterance_matches[utterance_index].append(capture_index)
        overlaps.sort(key=lambda item: (-item[0], item[1]))
        capture_matches[capture_index] = {"matched": overlaps[0][1] if overlaps else None,
                                          "overlap_count": len(overlaps), "overlaps": overlaps}
    return capture_matches, utterance_matches


def build_pipeline(profile):
    from configs import whisper as config
    from ..whisper.detector import create_speech_detector, create_whisper_detector
    from ..whisper.pipeline import DetectorPipeline
    profile_settings = dict(config.DETECTOR_PROFILES[profile])
    classifier = "temporal_v2" if profile in ("temporal_v2_context", "temporal_v2_recall") else "temporal_v1"
    settings = {**config.WHISPER_CLASSIFIER_SETTINGS, **profile_settings, "analysis_full": profile == "analysis_full"}
    whisper = create_whisper_detector(classifier, sample_rate=config.SAMPLE_RATE, rms_min=config.RMS_MIN,
        rms_max=config.RMS_MAX, zcr_min=config.ZCR_MIN, zcr_max=config.ZCR_MAX, entropy_min=config.ENTROPY_MIN,
        decision_window=config.DECISION_WINDOW, trigger_ratio=config.TRIGGER_RATIO, **settings)
    speech = create_speech_detector(config.SPEECH_DETECTOR_IMPLEMENTATION, sample_rate=config.SAMPLE_RATE,
        rms_min=config.SPEECH_RMS_MIN, rms_max=config.SPEECH_RMS_MAX, zcr_min=config.SPEECH_ZCR_MIN,
        zcr_max=config.SPEECH_ZCR_MAX, entropy_min=config.SPEECH_ENTROPY_MIN,
        centroid_min=config.SPEECH_CENTROID_MIN, centroid_max=config.SPEECH_CENTROID_MAX)
    comparisons = {}
    if profile in ("webrtc_assisted_temporal", "temporal_v2_context", "temporal_v2_recall"):
        mode = profile_settings["webrtc_aggressiveness"]
        comparisons[mode] = create_speech_detector("webrtc", sample_rate=config.SAMPLE_RATE, aggressiveness=mode)
    pipeline = DetectorPipeline(whisper, speech, config.PROCESSING_MODE,
                                comparison_speech_detectors=comparisons, classifier_implementation=classifier)
    return pipeline, TemporalProfilePolicy(profile, profile_settings), profile_settings, classifier


def captures_for_wav(wav_path, profile, policy):
    """Sequentially feed canonical WAV frames through Stage 3S and the shared engine."""
    from configs import whisper as config
    import soundfile as sf
    audio, rate = sf.read(wav_path, dtype="float32", always_2d=False)
    if rate != config.SAMPLE_RATE:
        raise ValueError(f"{wav_path}: expected {config.SAMPLE_RATE}Hz, got {rate}Hz")
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1, dtype=np.float32)
    audio = np.asarray(audio, dtype=np.float32)
    frame_samples = int(config.SAMPLE_RATE * config.FRAME_MS / 1000)
    pipeline, profile_policy, profile_settings, classifier = build_pipeline(profile)
    # Existing production capacity is 5s; preserve it when it already satisfies
    # policy and only extend locally if an override needs more history.
    ring = AudioRingBuffer(config.SAMPLE_RATE, max(config.BUFFER_SECONDS, policy.pre_roll_seconds))
    controller = UtteranceCaptureController(config.SAMPLE_RATE, ring, policy, wav_path.name, profile)
    last_trigger_time = -float("inf")
    triggers = []
    for frame_index, start in enumerate(range(0, len(audio), frame_samples)):
        frame = audio[start:start + frame_samples]
        if len(frame) < frame_samples:
            frame = np.pad(frame, (0, frame_samples - len(frame)))
        ring.append(frame)
        pipeline_result = pipeline.process(frame)
        result = pipeline_result.whisper
        assist = pipeline_result.speech_comparisons.get(profile_settings.get("webrtc_aggressiveness", 0))
        decision = profile_policy.update(result, assist)
        audio_time = (frame_index + 1) * frame_samples / float(config.SAMPLE_RATE)
        emitted_trigger = bool(decision.trigger and audio_time - last_trigger_time > config.COOLDOWN_SECONDS)
        if emitted_trigger:
            pipeline.record_trigger()
            last_trigger_time = audio_time
            triggers.append(audio_time)
        candidate = result.temporal_v2_raw_is_whisper if classifier == "temporal_v2" else result.temporal_v1_raw_is_whisper
        controller.process_frame(frame, frame_index, emitted_trigger=emitted_trigger, temporal_candidate=bool(candidate))
    controller.finish()
    return controller.completed, triggers


def _capture_rows_and_utterances(captures, utterances, profile):
    matches, utterance_matches = match_captures(captures, utterances)
    capture_rows = []
    for index, capture in enumerate(captures):
        match = matches[index]; utterance = utterances.loc[match["matched"]] if match["matched"] is not None else None
        start, end = capture.time(capture.capture_start_sample), capture.time(capture.final_end_sample)
        row = _capture_base_row(capture, profile)
        row.update(false_capture=utterance is None, merged_capture=match["overlap_count"] > 1,
                   matched_effective_utterance_id="" if utterance is None else utterance.effective_utterance_id)
        if utterance is None:
            row.update(start_clipped=False, end_clipped=False, complete_envelope_covered=False,
                       start_clipped_seconds=0.0, end_clipped_seconds=0.0,
                       extra_audio_before_seconds=np.nan, extra_audio_after_seconds=np.nan,
                       logical_endpoint_would_clip=False, logical_endpoint_end_clipped_seconds=np.nan)
        else:
            row.update(_coverage_metrics(start, end, utterance.ground_truth_start, utterance.ground_truth_end))
            logical_end = capture.time(capture.logical_end_sample)
            row["logical_endpoint_would_clip"] = bool(logical_end is not None and logical_end < utterance.ground_truth_end)
            row["logical_endpoint_end_clipped_seconds"] = 0.0 if logical_end is None else max(0.0, utterance.ground_truth_end - logical_end)
        capture_rows.append(row)
    utterance_rows = []
    for utterance_index, utterance in utterances.iterrows():
        related = utterance_matches[utterance_index]
        covered = [capture_rows[i] for i in related]
        selected = min(related, key=lambda i: (abs(captures[i].time(captures[i].trigger_sample) - utterance.ground_truth_start), i)) if related else None
        row = utterance.to_dict(); row.update(detector_profile=profile, was_triggered=bool(related), was_captured=bool(related),
            matched_capture_index="" if selected is None else selected, split_utterance=len(related) > 1,
            complete_envelope_covered=any(item["complete_envelope_covered"] for item in covered),
            start_clipped=any(item["start_clipped"] for item in covered) if covered else False,
            end_clipped=any(item["end_clipped"] for item in covered) if covered else False)
        if selected is None:
            row.update(trigger_time=np.nan, capture_start=np.nan, logical_capture_end=np.nan, final_capture_end=np.nan,
                       trigger_latency_from_utterance_start=np.nan, capture_duration=np.nan,
                       start_clipped_seconds=np.nan, end_clipped_seconds=np.nan,
                       extra_audio_before_seconds=np.nan, extra_audio_after_seconds=np.nan)
        else:
            chosen = capture_rows[selected]
            row.update({name: chosen[name] for name in ("trigger_time", "capture_start", "logical_capture_end", "final_capture_end", "capture_duration", "start_clipped_seconds", "end_clipped_seconds", "extra_audio_before_seconds", "extra_audio_after_seconds")})
            row["trigger_latency_from_utterance_start"] = chosen["trigger_time"] - utterance.ground_truth_start
        utterance_rows.append(row)
    return pd.DataFrame(capture_rows), pd.DataFrame(utterance_rows)


def _capture_base_row(capture, profile):
    return {"source_wav": capture.source_id, "capture_index": capture.capture_index, "detector_profile": profile,
            "trigger_frame": capture.trigger_frame, "trigger_time": capture.time(capture.trigger_sample),
            "capture_start_frame": capture.capture_start_frame, "capture_start": capture.time(capture.capture_start_sample),
            "logical_end_frame": capture.logical_end_frame, "logical_capture_end": capture.time(capture.logical_end_sample),
            "final_capture_end": capture.time(capture.final_end_sample), "capture_duration": len(capture.samples) / capture.sample_rate,
            "completion_reason": capture.completion_reason, "pre_roll_seconds": capture.pre_roll_requested_seconds,
            "pre_roll_available_seconds": capture.pre_roll_available_seconds, "end_silence_seconds": capture.end_silence_seconds,
            "post_roll_seconds": capture.post_roll_seconds, "max_utterance_seconds": capture.max_utterance_seconds,
            "ignored_trigger_count": capture.ignored_trigger_count}


def _coverage_metrics(capture_start, capture_end, truth_start, truth_end):
    start_clipped = capture_start > truth_start
    end_clipped = capture_end < truth_end
    return {"start_clipped": start_clipped, "end_clipped": end_clipped,
            "complete_envelope_covered": not start_clipped and not end_clipped,
            "start_clipped_seconds": max(0.0, capture_start - truth_start),
            "end_clipped_seconds": max(0.0, truth_end - capture_end),
            "extra_audio_before_seconds": max(0.0, truth_start - capture_start),
            "extra_audio_after_seconds": max(0.0, capture_end - truth_end)}


def summary_rows(captures, utterances):
    def count(column): return int(utterances[column].sum()) if len(utterances) else 0
    values = {"annotated_utterances": len(utterances), "trigger_recall": float(utterances.was_triggered.mean()) if len(utterances) else np.nan,
              "capture_recall": float(utterances.was_captured.mean()) if len(utterances) else np.nan,
              "complete_envelope_coverage_rate": float(utterances.complete_envelope_covered.mean()) if len(utterances) else np.nan,
              "start_clipping_count": count("start_clipped"), "end_clipping_count": count("end_clipped"),
              "false_capture_count": int(captures.false_capture.sum()) if len(captures) else 0,
              "merged_capture_count": int(captures.merged_capture.sum()) if len(captures) else 0,
              "split_capture_count": int(utterances.split_utterance.sum()) if len(utterances) else 0}
    for field in ("trigger_latency_from_utterance_start", "extra_audio_before_seconds", "extra_audio_after_seconds"):
        valid = pd.to_numeric(utterances.get(field, pd.Series(dtype=float)), errors="coerce").dropna()
        values[field + "_median"] = float(valid.median()) if len(valid) else np.nan
        values[field + "_min"] = float(valid.min()) if len(valid) else np.nan
        values[field + "_max"] = float(valid.max()) if len(valid) else np.nan
    for reason, total in captures.completion_reason.value_counts().items() if len(captures) else []:
        values[f"completion_{reason}_count"] = int(total)
    return pd.DataFrame([values])


def export_captures(captures, capture_rows, output_dir):
    import soundfile as sf
    clips = output_dir / "captured_wavs"; clips.mkdir()
    for capture, row in zip(captures, capture_rows.to_dict("records")):
        identity = row["matched_effective_utterance_id"] or "unmatched"
        name = f"{Path(capture.source_id).stem}_capture{capture.capture_index:03d}_{capture.detector_profile}_{identity}.wav"
        sf.write(clips / name, capture.samples, capture.sample_rate, subtype="PCM_16")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wav", type=Path); source.add_argument("--input-dir", type=Path)
    parser.add_argument("--annotation", type=Path, help="Required only when --wav cannot use annotations/<stem>.csv")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--detector-profile", choices=PROFILE_NAMES, default="temporal_v2_context")
    parser.add_argument("--pre-roll-seconds", type=float, default=4.0)
    parser.add_argument("--end-silence-seconds", type=float, default=1.5)
    parser.add_argument("--post-roll-seconds", type=float, default=0.5)
    parser.add_argument("--max-utterance-seconds", type=float, default=12.0)
    parser.add_argument("--export-captures", action="store_true")
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error(f"output directory already exists: {args.output_dir}")
    policy = CapturePolicy(args.pre_roll_seconds, args.end_silence_seconds, args.post_roll_seconds, args.max_utterance_seconds); policy.validate()
    wavs = [args.wav] if args.wav else sorted(args.input_dir.glob("*.wav"))
    if not wavs: parser.error("no WAV files found")
    args.output_dir.mkdir(parents=True)
    all_captures, all_utterances = [], []
    for wav in wavs:
        annotation = args.annotation if args.annotation and wav == args.wav else wav.parent / "annotations" / f"{wav.stem}.csv"
        if not annotation.exists(): raise FileNotFoundError(f"annotation CSV not found for {wav}: {annotation}")
        annotations = load_annotations(annotation, wav_root=wav.parent, default_wav_file=wav.name)
        captures, triggers = captures_for_wav(wav, args.detector_profile, policy)
        capture_rows, utterance_rows = _capture_rows_and_utterances(captures, utterance_envelopes(annotations), args.detector_profile)
        all_captures.extend(captures); all_utterances.append((capture_rows, utterance_rows))
    capture_table = pd.concat([item[0] for item in all_utterances], ignore_index=True)
    utterance_table = pd.concat([item[1] for item in all_utterances], ignore_index=True)
    summary = summary_rows(capture_table, utterance_table)
    capture_table.to_csv(args.output_dir / "capture_level.csv", index=False); utterance_table.to_csv(args.output_dir / "utterance_level.csv", index=False)
    summary.to_csv(args.output_dir / "summary.csv", index=False); (args.output_dir / "summary.json").write_text(json.dumps(summary.iloc[0].to_dict(), indent=2, default=str), encoding="utf-8")
    if args.export_captures: export_captures(all_captures, capture_table, args.output_dir)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
