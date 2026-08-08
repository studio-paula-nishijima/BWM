"""Pure offline utilities for comparing detector CSVs with interval annotations.

The live CSV ``timestamp`` is an emission wall-clock time, not an audio clock.
For WAV runs this module therefore uses an explicit elapsed-time column when one
is present, otherwise ``frame * frame_seconds`` (30 ms by default).
"""
from __future__ import annotations

import json
import warnings
import wave
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = {"wav_file", "start_seconds", "end_seconds", "label"}
LABELS = {"silence", "background_noise", "normal_speech", "whisper", "uncertain"}
OPTIONAL_COLUMNS = ("confidence", "strength", "speaker", "distance", "noise_type", "notes")
EXCLUDED_LABELS = {"uncertain"}


class AnnotationValidationError(ValueError):
    """An annotation file cannot safely be used for evaluation."""


def _truthy_column(frames, name, default=True):
    """Normalise logger booleans (CSV values may be strings or actual bools)."""
    value = frames.get(name)
    if value is None:
        return pd.Series(default, index=frames.index)
    return value.astype(str).str.lower().eq("true")


def wav_duration_seconds(path):
    """Read duration with the standard library so analysis has no audio dependency."""
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def load_annotations(path, wav_root=None, reject_overlaps=False, default_wav_file=None):
    """Load and validate an interval CSV without modifying it.

    Intervals use half-open semantics: ``[start_seconds, end_seconds)``.  This
    makes a frame on a shared boundary belong to the following segment.
    """
    annotations = pd.read_csv(path)
    # A one-file-per-recording annotation CSV can omit wav_file when its caller
    # supplies the recording name.  This is a convenience only; it is added to
    # the in-memory derived table and never written back to the source CSV.
    if "wav_file" not in annotations.columns and default_wav_file is not None:
        annotations.insert(0, "wav_file", Path(default_wav_file).name)
    missing = REQUIRED_COLUMNS - set(annotations.columns)
    if missing:
        raise AnnotationValidationError("Missing required columns: " + ", ".join(sorted(missing)))
    annotations = annotations.copy()
    annotations["wav_file"] = annotations["wav_file"].astype(str)
    annotations["label"] = annotations["label"].astype(str).str.strip().str.lower()
    bad_labels = sorted(set(annotations.loc[~annotations.label.isin(LABELS), "label"]))
    if bad_labels:
        raise AnnotationValidationError("Unrecognised labels: " + ", ".join(bad_labels))
    for column in ("start_seconds", "end_seconds"):
        annotations[column] = pd.to_numeric(annotations[column], errors="coerce")
    invalid = (~np.isfinite(annotations.start_seconds) | ~np.isfinite(annotations.end_seconds)
               | (annotations.start_seconds < 0) | (annotations.end_seconds <= annotations.start_seconds))
    if invalid.any():
        raise AnnotationValidationError("Times must be numeric, nonnegative, and end_seconds > start_seconds")
    root = Path(wav_root) if wav_root else Path(path).parent.parent
    for wav_name, group in annotations.groupby("wav_file", sort=False):
        wav_path = root / wav_name
        if wav_path.exists():
            duration = wav_duration_seconds(wav_path)
            if (group.end_seconds > duration + 1e-9).any():
                raise AnnotationValidationError(f"Intervals for {wav_name} exceed WAV duration ({duration:.3f}s)")
        ordered = group.sort_values(["start_seconds", "end_seconds"])
        overlaps = ordered.start_seconds.iloc[1:].to_numpy() < ordered.end_seconds.iloc[:-1].to_numpy()
        if overlaps.any():
            message = f"Overlapping annotation intervals found for {wav_name}; first matching interval is used"
            if reject_overlaps:
                raise AnnotationValidationError(message)
            warnings.warn(message, UserWarning, stacklevel=2)
    return annotations.sort_values(["wav_file", "start_seconds", "end_seconds"], kind="stable").reset_index(drop=True)


def derive_frame_times(records, frame_seconds=0.03):
    """Return copied records with frame_time_seconds, preferring audio-time fields."""
    records = records.copy()
    for name in ("frame_time_seconds", "elapsed_seconds", "time_seconds", "audio_time_seconds"):
        if name in records:
            records["frame_time_seconds"] = pd.to_numeric(records[name], errors="coerce")
            return records
    if "frame" not in records:
        raise ValueError("Detector CSV needs frame or an explicit elapsed-time column")
    records["frame_time_seconds"] = pd.to_numeric(records["frame"], errors="coerce") * frame_seconds
    return records


def join_frames_to_annotations(records, annotations, wav_file, frame_seconds=0.03):
    """Attach one interval's metadata to each detector frame; unmatched frames stay NA."""
    frames = derive_frame_times(records, frame_seconds)
    anns = annotations.loc[annotations.wav_file == Path(wav_file).name].copy()
    frames["wav_file"] = Path(wav_file).name
    frames["annotation_label"] = pd.NA
    frames["annotation_start_seconds"] = np.nan
    frames["annotation_end_seconds"] = np.nan
    for column in OPTIONAL_COLUMNS:
        frames[f"annotation_{column}"] = pd.NA
    # stable ordering means overlaps deterministically choose the earlier interval.
    for _, interval in anns.iterrows():
        mask = (frames.frame_time_seconds >= interval.start_seconds) & (frames.frame_time_seconds < interval.end_seconds)
        mask &= frames.annotation_label.isna()
        frames.loc[mask, "annotation_label"] = interval.label
        frames.loc[mask, "annotation_start_seconds"] = interval.start_seconds
        frames.loc[mask, "annotation_end_seconds"] = interval.end_seconds
        for column in OPTIONAL_COLUMNS:
            if column in anns:
                frames.loc[mask, f"annotation_{column}"] = interval.get(column)
    return frames


def feature_columns(frames):
    excluded = {"frame", "frame_time_seconds", "timestamp", "raw_score", "speech_probability", "whisper_probability"}
    return [c for c in frames.columns if c not in excluded and not c.startswith("annotation_")
            and pd.api.types.is_numeric_dtype(frames[c])]


def _percentile(values, q):
    return float(np.percentile(values, q)) if len(values) else np.nan


def feature_summary(frames, weighting="frame"):
    """Long-form per-label feature statistics; segment weighting avoids long segments dominating."""
    labelled = frames.loc[frames.annotation_label.notna() & ~frames.annotation_label.isin(EXCLUDED_LABELS)].copy()
    features = feature_columns(labelled)
    rows = []
    for label, group in labelled.groupby("annotation_label", dropna=False):
        segments = group.groupby(["wav_file", "annotation_start_seconds", "annotation_end_seconds"], dropna=False)
        for feature in features:
            values = group[feature]
            if weighting == "segment":
                values = segments[feature].mean()
            valid = values.dropna().to_numpy(dtype=float)
            rows.append({"label": label, "feature": feature, "weighting": weighting,
                         "frame_count": int(len(group)), "segment_count": int(segments.ngroups),
                         "mean": float(np.mean(valid)) if len(valid) else np.nan,
                         "median": float(np.median(valid)) if len(valid) else np.nan,
                         "std": float(np.std(valid, ddof=1)) if len(valid) > 1 else np.nan,
                         "p05": _percentile(valid, 5), "p25": _percentile(valid, 25),
                         "p75": _percentile(valid, 75), "p95": _percentile(valid, 95),
                         "min": float(np.min(valid)) if len(valid) else np.nan,
                         "max": float(np.max(valid)) if len(valid) else np.nan,
                         "missing_rate": float(values.isna().mean())})
    return pd.DataFrame(rows)


def _auc(y, score):
    pos, neg = y.sum(), len(y) - y.sum()
    if not pos or not neg:
        return np.nan
    ranks = pd.Series(score).rank(method="average").to_numpy()
    return float((ranks[y].sum() - pos * (pos + 1) / 2) / (pos * neg))


def _separation_rows(data, positive_labels, comparison, stage, weighting):
    data = data.loc[data.annotation_label.notna() & ~data.annotation_label.isin(EXCLUDED_LABELS)].copy().reset_index(drop=True)
    y = data.annotation_label.isin(positive_labels).to_numpy()
    rows = []
    for feature in feature_columns(data):
        subset = data[[feature]].dropna()
        ys = y[subset.index.to_numpy()]
        if weighting == "segment":
            work = data[["wav_file", "annotation_start_seconds", "annotation_end_seconds", "annotation_label", feature]].copy()
            work["positive"] = work.annotation_label.isin(positive_labels)
            work = work.groupby(["wav_file", "annotation_start_seconds", "annotation_end_seconds", "positive"], dropna=False)[feature].mean().reset_index()
            subset, ys = work[[feature]], work.positive.to_numpy()
        values = subset[feature].to_numpy(dtype=float)
        finite = np.isfinite(values)
        values, ys = values[finite], ys[finite]
        if len(values) < 2 or not ys.any() or ys.all():
            continue
        positive, negative = values[ys], values[~ys]
        median_difference = float(np.median(positive) - np.median(negative))
        pooled = np.sqrt((np.var(positive) + np.var(negative)) / 2)
        effect = median_difference / pooled if pooled else np.nan
        auc = _auc(ys, values)
        direction = 1 if median_difference >= 0 else -1
        candidates = np.unique(values)
        best = None
        for threshold in candidates:
            predicted = values >= threshold if direction > 0 else values <= threshold
            tp, fp = int((predicted & ys).sum()), int((predicted & ~ys).sum())
            fn, tn = int((~predicted & ys).sum()), int((~predicted & ~ys).sum())
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            candidate = (f1, threshold, precision, recall, tn, fp, fn, tp)
            if best is None or candidate[0] > best[0]: best = candidate
        # overlap coefficient estimated as shared histogram mass (documented in output).
        # ``auto`` can derive an impractically tiny width when a mostly-flat
        # feature has an outlier, producing millions of bins.  A bounded
        # count keeps this descriptive overlap metric safe for raw logs.
        if values.min() == values.max():
            overlap = 1.0
        else:
            bin_count = min(32, max(2, int(np.sqrt(len(values)))))
            bins = np.linspace(values.min(), values.max(), bin_count + 1)
            hp, _ = np.histogram(positive, bins=bins, density=True); hn, _ = np.histogram(negative, bins=bins, density=True)
            overlap = float(np.minimum(hp, hn).sum() * np.diff(bins).mean())
        rows.append({"stage": stage, "comparison": comparison, "feature": feature, "weighting": weighting,
                     "median_difference": median_difference, "effect_size": effect, "roc_auc": auc,
                     "distribution_overlap": overlap, "overlap_measure": "shared_histogram_mass",
                     "candidate_threshold": float(best[1]), "threshold_direction": ">=" if direction > 0 else "<=",
                     "precision": best[2], "recall": best[3], "f1": best[0], "tn": best[4], "fp": best[5], "fn": best[6], "tp": best[7],
                     "confusion_matrix": json.dumps([[best[4], best[5]], [best[6], best[7]]])})
    return rows


def feature_separation(frames, weighting="frame", full_pipeline=False):
    rows = []
    whisper = frames if full_pipeline else frames.loc[_truthy_column(frames, "whisper_processed")]
    rows += _separation_rows(whisper.loc[whisper.annotation_label.isin(["whisper", "normal_speech"])], {"whisper"}, "whisper_vs_normal_speech", "whisper", weighting)
    rows += _separation_rows(whisper, {"whisper"}, "whisper_vs_all_non_whisper", "whisper", weighting)
    speech = frames.loc[frames.annotation_label.isin(["normal_speech", "whisper", "silence", "background_noise"])]
    rows += _separation_rows(speech, {"normal_speech", "whisper"}, "speech_vs_non_speech", "speech", weighting)
    return pd.DataFrame(rows)


def _metric_row(stage, evaluation_unit, scope, truth, prediction, valid, full_pipeline=False):
    """Return a named binary metric row without hiding its comparison scope."""
    y = truth[valid].to_numpy(dtype=bool)
    p = prediction[valid].astype(str).str.lower().eq("true").to_numpy()
    tp, fp = int((p & y).sum()), int((p & ~y).sum())
    fn, tn = int((~p & y).sum()), int((~p & ~y).sum())
    return {"stage": stage, "evaluation_unit": evaluation_unit, "comparison_scope": scope,
            "full_pipeline": full_pipeline, "frame_count": int(valid.sum()), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp/(tp+fp) if tp+fp else np.nan, "recall": tp/(tp+fn) if tp+fn else np.nan,
            "f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else np.nan}


def _segment_trigger_metrics(frames, full_pipeline):
    """Evaluate sustained evidence and emitted triggers once per annotation segment."""
    required = {"wav_file", "annotation_start_seconds", "annotation_end_seconds", "annotation_label"}
    if not required.issubset(frames.columns):
        return []
    labelled = frames.loc[frames.annotation_label.notna() & ~frames.annotation_label.isin(EXCLUDED_LABELS)].copy()
    rows = []
    for keys, segment in labelled.groupby(["wav_file", "annotation_start_seconds", "annotation_end_seconds", "annotation_label"], dropna=False):
        qualifying = pd.to_numeric(segment.get("temporal_v1_qualifying_run", pd.Series(np.nan, index=segment.index)), errors="coerce")
        requirement = pd.to_numeric(segment.get("confirmation_requirement", pd.Series(np.nan, index=segment.index)), errors="coerce")
        rows.append({"annotation_label": keys[-1],
                     "sustained": bool((qualifying >= requirement).fillna(False).any()),
                     "trigger": bool(_truthy_column(segment, "trigger", default=False).any())})
    segments = pd.DataFrame(rows)
    if segments.empty:
        return []
    truth = segments.annotation_label.eq("whisper")
    return [
        _metric_row("whisper_sustained_segment", "annotation_segment", "whisper_vs_all_non_whisper", truth, segments.sustained,
                    pd.Series(True, index=segments.index), full_pipeline),
        _metric_row("whisper_trigger_segment", "annotation_segment", "whisper_vs_all_non_whisper", truth, segments.trigger,
                    pd.Series(True, index=segments.index), full_pipeline),
    ]


def evaluation_summary(frames, full_pipeline=False):
    rows = []
    labels = frames.annotation_label
    all_labels = labels.isin(["whisper", "normal_speech", "silence", "background_noise"])
    if frames.get("is_speech") is not None:
        valid = all_labels & frames.is_speech.notna()
        rows.append(_metric_row("speech_vs_non_speech", "frame", "speech_vs_non_speech",
                                labels.isin(["normal_speech", "whisper"]), frames.is_speech, valid, full_pipeline))
    if frames.get("is_whisper") is not None:
        processed = pd.Series(True, index=frames.index) if full_pipeline else _truthy_column(frames, "whisper_processed")
        for stage, scope, subset in (
            ("whisper_vs_normal_speech", "whisper_vs_normal_speech", labels.isin(["whisper", "normal_speech"])),
            ("whisper_vs_all_non_whisper", "whisper_vs_all_non_whisper", all_labels),
        ):
            valid = subset & processed & frames.is_whisper.notna()
            rows.append(_metric_row(stage, "frame", scope, labels.eq("whisper"), frames.is_whisper, valid, full_pipeline))
    rows.extend(_segment_trigger_metrics(frames, full_pipeline))
    comparison_columns = [("webrtc", frames.get("comparison_speech_is_speech"))]
    comparison_columns += [(f"webrtc_mode_{mode}", frames.get(f"webrtc_mode_{mode}_is_speech")) for mode in range(4)]
    for backend, comparison in comparison_columns:
        if comparison is None:
            continue
        for label, truth in (("webrtc_whisper_recall", labels.eq("whisper")), ("webrtc_normal_speech_recall", labels.eq("normal_speech")),
                             ("webrtc_silence_false_speech", labels.eq("silence")), ("webrtc_background_false_speech", labels.eq("background_noise"))):
            valid = truth & labels.notna() & ~labels.isin(EXCLUDED_LABELS) & comparison.notna()
            positives = comparison[valid].astype(str).str.lower().eq("true")
            rows.append({"stage": f"{backend}_{label.removeprefix('webrtc_')}", "evaluation_unit": "frame", "comparison_scope": label, "full_pipeline": full_pipeline, "frame_count": int(valid.sum()),
                         "tp": int(positives.sum()), "fp": np.nan, "fn": int((~positives).sum()), "tn": np.nan,
                         "precision": np.nan, "recall": float(positives.mean()) if len(positives) else np.nan, "f1": np.nan})
    return pd.DataFrame(rows)


def qualifying_run_summary(frames, column="temporal_v1_raw_is_whisper"):
    """Return each labelled segment's maximum consecutive qualifying-frame run."""
    if column not in frames:
        return pd.DataFrame(columns=["wav_file", "annotation_start_seconds", "annotation_end_seconds", "annotation_label", "max_qualifying_run"])
    rows = []
    labelled = frames.loc[frames.annotation_label.notna()]
    for keys, segment in labelled.groupby(["wav_file", "annotation_start_seconds", "annotation_end_seconds", "annotation_label"], dropna=False):
        flags = segment[column].astype(str).str.lower().eq("true").to_numpy()
        run = maximum = 0
        for flag in flags:
            run = run + 1 if flag else 0
            maximum = max(maximum, run)
        rows.append(dict(zip(["wav_file", "annotation_start_seconds", "annotation_end_seconds", "annotation_label"], keys), max_qualifying_run=maximum))
    return pd.DataFrame(rows)


def analyse_triplets(triplets, output_dir, frame_seconds=0.03, weighting="frame", full_pipeline=False, reject_overlaps=False, analysis_tag=None):
    """Analyse iterable of (wav_path, log_path, annotation_path) and write the four exports."""
    all_frames = []
    for wav_path, log_path, annotation_path in triplets:
        wav_path = Path(wav_path)
        anns = load_annotations(annotation_path, wav_root=wav_path.parent,
                                reject_overlaps=reject_overlaps,
                                default_wav_file=wav_path.name)
        all_frames.append(join_frames_to_annotations(pd.read_csv(log_path), anns, wav_path.name, frame_seconds))
    frames = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()
    output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    summaries = pd.concat([feature_summary(frames, mode) for mode in ("frame", "segment")], ignore_index=True)
    separation = pd.concat([feature_separation(frames, mode, full_pipeline) for mode in ("frame", "segment")], ignore_index=True)
    evaluation = evaluation_summary(frames, full_pipeline)
    qualifying_runs = qualifying_run_summary(frames)
    suffix = f"_{analysis_tag}" if analysis_tag else ""
    frames.to_csv(output / f"labelled_frames{suffix}.csv", index=False)
    summaries.to_csv(output / f"feature_summary{suffix}.csv", index=False)
    separation.to_csv(output / f"feature_separation{suffix}.csv", index=False)
    evaluation.to_csv(output / f"evaluation_summary{suffix}.csv", index=False)
    qualifying_runs.to_csv(output / f"qualifying_run_summary{suffix}.csv", index=False)
    return {"labelled_frames": frames, "feature_summary": summaries, "feature_separation": separation, "evaluation_summary": evaluation, "qualifying_run_summary": qualifying_runs}
