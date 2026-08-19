"""Offline normal-speech-context policy evaluation for labelled detector logs.

This module consumes labelled frames only.  It never participates in live
detector, trigger, actuation, acquisition, or WAV-processing behaviour.
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .labelled_wav import EXCLUDED_LABELS, _truthy_column


CONTEXT_WINDOWS_SECONDS = (0.6, 1.0, 1.5)
HIGH_SILERO_FRACTIONS = (0.1, 0.2, 0.3)
PENALTY_REQUIREMENTS = (24, 30, 36)
HIGH_SILERO_THRESHOLD = 0.5

KNOWN_PAULA_PASSAGES = (
    ("paula_s_1m_2", "3_paula_speak_1m_2.wav", ((3.39, 4.59),), "3.39-4.59; base crossing 3.81"),
    ("paula_s_1m_1", "3_paula_speak_1m_1.wav", ((8.13, 8.79), (9.03, 10.00)), "8.13-8.79 and 9.03-10.00; reported trigger 8.55"),
)


def _normalise_frames(frames):
    work = frames.copy()
    work["frame_time_seconds"] = pd.to_numeric(work["frame_time_seconds"], errors="coerce")
    work["speech_probability"] = pd.to_numeric(work.get("speech_probability"), errors="coerce").fillna(0.0)
    work["base_candidate"] = _truthy_column(work, "temporal_v1_raw_is_whisper", default=False)
    requirement = pd.to_numeric(work.get("confirmation_requirement"), errors="coerce")
    work["existing_requirement"] = requirement.fillna(24).astype(int)
    return work.sort_values(["wav_file", "frame_time_seconds", "frame"], kind="stable").reset_index(drop=True)


def _candidate_runs(candidate):
    run, result = 0, []
    for value in candidate:
        run = run + 1 if value else 0
        result.append(run)
    return np.asarray(result, dtype=int)


def _crossings(above):
    previous = False
    result = []
    for value in above:
        value = bool(value)
        result.append(value and not previous)
        previous = value
    return np.asarray(result, dtype=bool)


def evaluate_context_policy(frames, context_window_seconds, high_silero_fraction, penalty_requirement):
    """Evaluate one policy without resetting state at annotation boundaries."""
    work = _normalise_frames(frames)
    parts = []
    for _, wav in work.groupby("wav_file", sort=False):
        wav = wav.copy().reset_index(drop=True)
        times = wav.frame_time_seconds.to_numpy(dtype=float)
        high = wav.speech_probability.to_numpy(dtype=float) >= HIGH_SILERO_THRESHOLD
        fraction = np.zeros(len(wav), dtype=float)
        left = 0
        for index, now in enumerate(times):
            while left < index and times[left] < now - context_window_seconds:
                left += 1
            fraction[index] = high[left:index + 1].mean()
        context_present = fraction >= high_silero_fraction
        candidate = wav.base_candidate.to_numpy(dtype=bool)
        live_run = _candidate_runs(candidate)
        base_requirement = wav.existing_requirement.to_numpy(dtype=int)
        effective_requirement = np.where(context_present, np.maximum(base_requirement, penalty_requirement), base_requirement)
        base_above = candidate & (live_run >= base_requirement)
        policy_above = candidate & (live_run >= effective_requirement)
        wav["context_high_silero_fraction"] = fraction
        wav["normal_speech_context_present"] = context_present
        wav["context_penalty_requirement"] = int(penalty_requirement)
        wav["effective_confirmation_requirement"] = effective_requirement
        wav["live_candidate_run"] = live_run
        wav["base_threshold_crossing"] = _crossings(base_above)
        wav["policy_threshold_crossing"] = _crossings(policy_above)
        wav["policy_above_requirement"] = policy_above
        wav["segment_local_candidate_run"] = 0
        wav["segment_local_above_requirement"] = False
        labelled = wav.annotation_label.notna()
        keys = ["annotation_start_seconds", "annotation_end_seconds", "annotation_label"]
        for _, segment in wav.loc[labelled].groupby(keys, dropna=False, sort=False):
            local_run = _candidate_runs(segment.base_candidate.to_numpy(dtype=bool))
            local_above = segment.base_candidate.to_numpy(dtype=bool) & (local_run >= segment.effective_confirmation_requirement.to_numpy(dtype=int))
            wav.loc[segment.index, "segment_local_candidate_run"] = local_run
            wav.loc[segment.index, "segment_local_above_requirement"] = local_above
        wav["cross_boundary_continuation"] = wav.policy_above_requirement & ~wav.segment_local_above_requirement
        parts.append(wav)
    return pd.concat(parts, ignore_index=True) if parts else work


def _notes(frame):
    return frame.get("annotation_notes", pd.Series("", index=frame.index)).fillna("").astype(str).str.lower()


def _speaker(frame):
    value = frame.get("annotation_speaker_id")
    if value is None:
        value = frame.get("annotation_speaker", pd.Series(pd.NA, index=frame.index))
    return value.fillna("unknown").astype(str)


def _segment_summary(data, scope, speaker_id=""):
    keys = ["wav_file", "annotation_start_seconds", "annotation_end_seconds", "annotation_label"]
    data = data.loc[data.annotation_label.notna() & ~data.annotation_label.isin(EXCLUDED_LABELS)].copy()
    if data.empty:
        return dict(scope=scope, speaker_id=speaker_id, segment_count=0, frame_count=0,
                    candidate_positive_segments=0, live_positive_segments=0, segment_local_positive_segments=0,
                    max_live_qualifying_run=0, max_segment_local_qualifying_run=0,
                    live_threshold_crossings=0, segment_local_threshold_crossings=0,
                    cross_boundary_segments=0, cross_boundary_frames=0, policy_positive_frames=0)
    segments = list(data.groupby(keys, dropna=False, sort=False))
    return dict(
        scope=scope,
        speaker_id=speaker_id,
        segment_count=len(segments),
        frame_count=int(len(data)),
        candidate_positive_segments=sum(bool(group.base_candidate.any()) for _, group in segments),
        live_positive_segments=sum(bool(group.policy_above_requirement.any()) for _, group in segments),
        segment_local_positive_segments=sum(bool(group.segment_local_above_requirement.any()) for _, group in segments),
        max_live_qualifying_run=max(int(group.live_candidate_run.max()) for _, group in segments),
        max_segment_local_qualifying_run=max(int(group.segment_local_candidate_run.max()) for _, group in segments),
        live_threshold_crossings=int(data.policy_threshold_crossing.sum()),
        segment_local_threshold_crossings=sum(int(_crossings(group.segment_local_above_requirement.to_numpy()).sum()) for _, group in segments),
        cross_boundary_segments=sum(bool(group.cross_boundary_continuation.any()) for _, group in segments),
        cross_boundary_frames=int(data.cross_boundary_continuation.sum()),
        policy_positive_frames=int(data.policy_above_requirement.sum()),
    )


def _scope_rows(policy_frames):
    notes = _notes(policy_frames)
    labels = policy_frames.annotation_label
    rows = []
    whisper = policy_frames.loc[labels.eq("whisper")]
    for speaker_id, speaker_frames in whisper.groupby(_speaker(whisper), sort=True):
        rows.append(_segment_summary(speaker_frames, "whisper_by_speaker", speaker_id))
    rows.append(_segment_summary(whisper, "all_whisper"))
    rows.append(_segment_summary(whisper.loc[~_notes(whisper).str.contains("very quiet", regex=False)], "all_whisper_excluding_very_quiet"))
    normal = policy_frames.loc[labels.eq("normal_speech")]
    normal_notes = _notes(normal)
    rows.append(_segment_summary(normal.loc[~normal_notes.str.contains("phone_audio", regex=False)], "direct_microphone_normal_speech"))
    rows.append(_segment_summary(normal.loc[normal_notes.str.contains("phone_audio", regex=False)], "phone_audio_normal_speech"))
    # Notes such as non-verbal vocalisation can be applied to a `silence`
    # interval, so named sound categories intentionally span every
    # non-whisper label rather than only `background_noise`.
    non_whisper = policy_frames.loc[~labels.isin(["whisper", *EXCLUDED_LABELS])]
    non_whisper_notes = _notes(non_whisper)
    categories = {
        "laughter_background": non_whisper_notes.str.contains("laughter", regex=False),
        "non_verbal_background": non_whisper_notes.str.contains("non_verbal", regex=False),
        "breathing_background": non_whisper_notes.str.contains("breath", regex=False),
        "buzzing_background": non_whisper_notes.str.contains("buzz", regex=False),
    }
    allocated = pd.Series(False, index=non_whisper.index)
    for name, mask in categories.items():
        rows.append(_segment_summary(non_whisper.loc[mask], name))
        allocated |= mask
    background = non_whisper.loc[labels.loc[non_whisper.index].eq("background_noise")]
    rows.append(_segment_summary(background.loc[~allocated.reindex(background.index, fill_value=False)], "other_background"))
    return rows


def _known_passage_rows(policy_frames):
    rows = []
    for passage_id, wav_file, intervals, description in KNOWN_PAULA_PASSAGES:
        wav = policy_frames.loc[policy_frames.wav_file.eq(wav_file)]
        mask = pd.Series(False, index=wav.index)
        for start, end in intervals:
            mask |= wav.frame_time_seconds.between(start, end, inclusive="both")
        passage = wav.loc[mask]
        rows.append(dict(
            row_type="known_paula_passage", scope="known_paula_s_false_positive", speaker_id="paula",
            passage_id=passage_id, passage_description=description,
            passage_candidate_frames=int(passage.base_candidate.sum()),
            base_threshold_crossings=int(passage.base_threshold_crossing.sum()),
            policy_threshold_crossings=int(passage.policy_threshold_crossing.sum()),
            passage_rejected=bool(passage.base_candidate.any() and not passage.policy_threshold_crossing.any()),
            segment_count=0, frame_count=int(len(passage)), candidate_positive_segments=0,
            live_positive_segments=0, segment_local_positive_segments=0,
            max_live_qualifying_run=int(passage.live_candidate_run.max()) if not passage.empty else 0,
            max_segment_local_qualifying_run=int(passage.segment_local_candidate_run.max()) if not passage.empty else 0,
            live_threshold_crossings=0, segment_local_threshold_crossings=0,
            cross_boundary_segments=0, cross_boundary_frames=0, policy_positive_frames=int(passage.policy_above_requirement.sum()),
        ))
    return rows


def run_context_sweep(frames):
    """Return a long-form report for all requested context-policy combinations."""
    report = []
    for window, fraction, penalty in product(CONTEXT_WINDOWS_SECONDS, HIGH_SILERO_FRACTIONS, PENALTY_REQUIREMENTS):
        policy = evaluate_context_policy(frames, window, fraction, penalty)
        policy_id = f"w{window:g}_f{fraction:g}_r{penalty}"
        metadata = dict(row_type="scope_summary", policy_id=policy_id,
                        context_window_seconds=window, high_silero_threshold=HIGH_SILERO_THRESHOLD,
                        recent_high_silero_fraction_threshold=fraction, penalty_requirement=penalty,
                        passage_id="", passage_description="", passage_candidate_frames=np.nan,
                        base_threshold_crossings=np.nan, policy_threshold_crossings=np.nan, passage_rejected=pd.NA)
        for row in _scope_rows(policy):
            report.append({**metadata, **row})
        for row in _known_passage_rows(policy):
            report.append({**metadata, **row})
    return pd.DataFrame(report)
