#!/usr/bin/env python3
"""Export the authoritative Translation score/config for autonomous ESP32 firmware."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml

CONVERTER_VERSION = "1"
MAX_PULSE_MS = 500
UINT32_MAX = (1 << 32) - 1
UINT16_MAX = (1 << 16) - 1
REQUIRED_FIELDS = {"playback_time", "timestamp", "type", "target", "action", "duration", "metadata"}


class ExportError(ValueError):
    pass


@dataclass(frozen=True)
class Event:
    time_ms: int
    duration_ms: int
    channel: int
    timestamp: str
    target: str


@dataclass(frozen=True)
class Result:
    source_sha256: str
    config_sha256: str
    source_count: int
    filtered_count: int
    source_playback_min: float
    source_playback_max: float
    filtered_playback_min: float
    filtered_playback_max: float
    first_timestamp: str
    last_timestamp: str
    events: tuple[Event, ...]
    per_target: dict[str, int]
    max_time_error_ms: float
    min_off_ms: int | None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _round_ms(seconds: float) -> int:
    return int(math.floor(seconds * 1000.0 + 0.5))


def _numeric(value: Any, label: str, index: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ExportError(f"event {index}: {label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ExportError(f"event {index}: {label} must be finite")
    return result


def _date(value: Any, index: int) -> np.datetime64:
    try:
        result = np.datetime64(value)
    except Exception as exc:
        raise ExportError(f"event {index}: invalid timestamp {value!r}") from exc
    if np.isnat(result):
        raise ExportError(f"event {index}: timestamp is NaT")
    return result


def load_config(translation_root: Path) -> tuple[dict, dict, str]:
    paths = [
        translation_root / "configs" / "runtime.yaml",
        translation_root / "configs" / "channels.yaml",
        translation_root / "configs" / "hardware.yaml",
        translation_root / "configs" / "voice_reactions.yaml",
    ]
    documents = []
    digest = hashlib.sha256()
    for path in paths:
        raw = path.read_bytes()
        digest.update(path.name.encode("utf-8") + b"\0" + raw)
        documents.append(yaml.safe_load(raw) or {})
    runtime, channels, _, reactions = documents
    channel_names = list(channels.get("channels", {}))
    if channel_names != [f"solenoid_{i}" for i in range(1, 7)]:
        raise ExportError(f"expected ordered six-channel topology, got {channel_names!r}")
    return runtime, reactions, digest.hexdigest()


def convert(array: np.ndarray, *, source_sha256: str, config_sha256: str,
            start_date: str, end_date: str, channel_names: Sequence[str]) -> Result:
    if not isinstance(array, np.ndarray) or array.ndim != 1 or array.size == 0:
        raise ExportError("score must be a non-empty one-dimensional NumPy array")
    mapping = {name: i for i, name in enumerate(channel_names)}
    start = np.datetime64(start_date)
    end_exclusive = np.datetime64(end_date) + np.timedelta64(1, "D")
    validated = []
    source_times = []
    for index, record in enumerate(array.tolist()):
        if not isinstance(record, dict):
            raise ExportError(f"event {index}: expected dict")
        missing = REQUIRED_FIELDS.difference(record)
        if missing:
            raise ExportError(f"event {index}: missing fields {sorted(missing)}")
        if record["type"] != "solenoid" or record["action"] != "pulse":
            raise ExportError(f"event {index}: unsupported type/action")
        target = record["target"]
        if target not in mapping:
            raise ExportError(f"event {index}: unsupported target {target!r}")
        playback = _numeric(record["playback_time"], "playback_time", index)
        duration = _numeric(record["duration"], "duration", index)
        timestamp = _date(record["timestamp"], index)
        if playback < 0 or duration <= 0:
            raise ExportError(f"event {index}: playback/duration outside valid range")
        duration_ms = _round_ms(duration)
        if not 0 < duration_ms <= MAX_PULSE_MS:
            raise ExportError(f"event {index}: pulse is outside 1..{MAX_PULSE_MS} ms")
        source_times.append(playback)
        if start <= timestamp < end_exclusive:
            validated.append((playback, duration_ms, mapping[target], str(timestamp), target))
    if not validated:
        raise ExportError("date filter removed every event")
    validated.sort(key=lambda item: item[0])
    origin = validated[0][0]
    events = []
    errors = []
    for playback, duration_ms, channel, timestamp, target in validated:
        exact = (playback - origin) * 1000.0
        time_ms = _round_ms(playback - origin)
        if time_ms > UINT32_MAX or duration_ms > UINT16_MAX:
            raise ExportError("generated integer overflow")
        events.append(Event(time_ms, duration_ms, channel, timestamp, target))
        errors.append(abs(time_ms - exact))
    per_channel: dict[int, list[Event]] = defaultdict(list)
    for event in events:
        per_channel[event.channel].append(event)
    off_intervals = [
        current.time_ms - (previous.time_ms + previous.duration_ms)
        for items in per_channel.values()
        for previous, current in zip(items, items[1:])
    ]
    return Result(
        source_sha256=source_sha256,
        config_sha256=config_sha256,
        source_count=int(array.size),
        filtered_count=len(events),
        source_playback_min=min(source_times),
        source_playback_max=max(source_times),
        filtered_playback_min=validated[0][0],
        filtered_playback_max=validated[-1][0],
        first_timestamp=validated[0][3],
        last_timestamp=validated[-1][3],
        events=tuple(events),
        per_target=dict(sorted(Counter(item.target for item in events).items())),
        max_time_error_ms=max(errors),
        min_off_ms=min(off_intervals, default=None),
    )


def load_and_convert(translation_root: Path) -> tuple[Result, dict, dict]:
    runtime, reactions, config_sha = load_config(translation_root)
    source = translation_root / runtime["files"]["events_file"]
    try:
        array = np.load(source, allow_pickle=True)
    except Exception as exc:
        raise ExportError(f"cannot load {source}: {exc}") from exc
    playback = runtime["playback"]
    result = convert(
        array,
        source_sha256=_sha(source),
        config_sha256=config_sha,
        start_date=playback["start_date"],
        end_date=playback["end_date"],
        channel_names=list(yaml.safe_load((translation_root / "configs" / "channels.yaml").read_text())["channels"]),
    )
    return result, runtime, reactions


def write_csv(result: Result, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(f"# source_sha256={result.source_sha256}\n# config_sha256={result.config_sha256}\n")
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("time_ms", "channel", "duration_ms", "target", "timestamp"))
        for event in result.events:
            writer.writerow((event.time_ms, event.channel, event.duration_ms, event.target, event.timestamp))


def write_header(result: Result, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"    {{{event.time_ms}u, {event.duration_ms}u, {event.channel}u}},"
        for event in result.events
    )
    content = f'''#pragma once
// Generated by tools/export_score.py v{CONVERTER_VERSION}; do not hand-edit.
// source SHA-256: {result.source_sha256}
// config SHA-256: {result.config_sha256}
#include "runtime_core.h"
namespace bwm {{
constexpr ScoreEvent kScoreEvents[] = {{
{rows}
}};
constexpr size_t kScoreEventCount = sizeof(kScoreEvents) / sizeof(kScoreEvents[0]);
constexpr uint32_t kScoreDurationMs = {result.events[-1].time_ms}u;
constexpr char kScoreSourceSha256[] = "{result.source_sha256}";
constexpr char kScoreConfigSha256[] = "{result.config_sha256}";
}}  // namespace bwm
'''
    path.write_text(content, encoding="utf-8", newline="\n")


def _ms(value: Any) -> int:
    return _round_ms(float(value))


def write_artistic_config(runtime: dict, reactions: dict, path: Path) -> None:
    playback = runtime["playback"]
    whisper = runtime["whisper_interaction"]
    strategies = reactions["strategies"]
    bands = whisper["silero_selection_bands"]
    expected = ["voice_band_1", "voice_band_2", "voice_band_3", "voice_band_4", "voice_band_5"]
    policies = reactions["policies"]
    names = [policies[name]["strategy"] for name in expected]
    reaction_ids = {name: i for i, name in enumerate(strategies)}
    if set(strategies) != {"voice_simultaneous_then_sequence", "voice_cascade", "voice_triple_tap", "voice_split_groups", "voice_double_tap"}:
        raise ExportError("production reaction repertoire changed; exporter requires review")
    weighted = reactions["policy"]
    if weighted.get("mode") != "weighted":
        raise ExportError("voice_default must remain a weighted policy")
    weights = [int(weighted["choices"].get(name, 0)) for name in strategies]
    upper = [float(band["upper_exclusive"]) for band in bands]
    header = f'''#pragma once
// Generated from runtime.yaml and voice_reactions.yaml; do not hand-edit.
#include <cmath>
#include <cstdint>
namespace bwm {{
constexpr bool kInitiallyActive = {str(bool(playback['initially_active'])).lower()};
constexpr uint32_t kSessionTimeoutMs = {_ms(playback['session_timeout_seconds'])}u;
constexpr uint32_t kSegmentDurationMs = {_ms(playback['segment_minutes'] * 60)}u;
constexpr uint32_t kSolenoidAdmissionDelayMs = {_ms(runtime['lighting']['activation_fade_seconds'])}u;
constexpr uint16_t kReactionPulseMs = 150u;
enum class Reaction : uint8_t {{ kSimultaneousThenSequence, kCascade, kTripleTap, kSplitGroups, kDoubleTap }};
constexpr float kSileroUpper[5] = {{{', '.join('INFINITY' if math.isinf(v) else repr(v) + 'f' for v in upper)}}};
constexpr Reaction kBandReaction[5] = {{{', '.join('static_cast<Reaction>(' + str(reaction_ids[n]) + ')' for n in names)}}};
constexpr uint8_t kDefaultWeights[5] = {{{', '.join(map(str, weights))}}};
constexpr uint32_t kQuietGapMs = {_ms(strategies['voice_cascade']['initial_quiet_gap_seconds'])}u;
constexpr uint32_t kSimultaneousWaitMs = {_ms(strategies['voice_simultaneous_then_sequence']['phases'][1]['duration_seconds'])}u;
constexpr uint32_t kSimultaneousSpacingMs = {_ms(strategies['voice_simultaneous_then_sequence']['phases'][2]['spacing_seconds'])}u;
constexpr uint32_t kSimultaneousTailMs = {_ms(strategies['voice_simultaneous_then_sequence']['phases'][3]['duration_seconds'])}u;
constexpr uint32_t kCascadeSpacingMs = {_ms(strategies['voice_cascade']['phases'][0]['spacing_seconds'])}u;
constexpr uint32_t kCascadeTailMs = {_ms(strategies['voice_cascade']['phases'][1]['duration_seconds'])}u;
constexpr uint32_t kSplitWaitMs = {_ms(strategies['voice_split_groups']['phases'][1]['duration_seconds'])}u;
constexpr uint32_t kSplitTailMs = {_ms(strategies['voice_split_groups']['phases'][3]['duration_seconds'])}u;
constexpr uint32_t kTripleWindowMs = {_ms(strategies['voice_triple_tap']['duration_seconds'])}u;
constexpr uint8_t kTripleCount = {int(strategies['voice_triple_tap']['repeat_count'])}u;
constexpr uint32_t kTripleSpacingMs = {_ms(strategies['voice_triple_tap']['tap_spacing_seconds'])}u;
constexpr uint32_t kDoubleWindowMs = {_ms(strategies['voice_double_tap']['duration_seconds'])}u;
constexpr uint8_t kDoubleCount = {int(strategies['voice_double_tap']['repeat_count'])}u;
constexpr uint32_t kDoubleSpacingMs = {_ms(strategies['voice_double_tap']['tap_spacing_seconds'])}u;
}}  // namespace bwm
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header, encoding="utf-8", newline="\n")


def format_report(result: Result) -> str:
    return "\n".join([
        "# Autonomous ESP32 Translation score report",
        "",
        f"- Converter version: `{CONVERTER_VERSION}`",
        f"- Source SHA-256: `{result.source_sha256}`",
        f"- Configuration SHA-256: `{result.config_sha256}`",
        f"- Source events: {result.source_count}",
        f"- Source playback range: {result.source_playback_min:.9f}–{result.source_playback_max:.9f} s",
        f"- Filtered events: {result.filtered_count}",
        f"- Filtered source playback range: {result.filtered_playback_min:.9f}–{result.filtered_playback_max:.9f} s",
        f"- Filtered timestamp range: {result.first_timestamp}–{result.last_timestamp}",
        f"- Embedded rebased duration: {result.events[-1].time_ms} ms",
        f"- Per-target counts: `{result.per_target}`",
        f"- Pulse duration: {min(e.duration_ms for e in result.events)}–{max(e.duration_ms for e in result.events)} ms",
        f"- Minimum quantized same-channel OFF interval: {result.min_off_ms} ms",
        f"- Maximum time quantization error: {result.max_time_error_ms:.6f} ms",
        f"- Generated table payload: {len(result.events) * 8} bytes (`ScoreEvent` is 8 bytes on ESP32)",
        "- Malformed/unsupported records: 0",
    ]) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--translation-root", type=Path, default=root.parent)
    parser.add_argument("--csv", type=Path, default=root / "generated" / "events.csv")
    parser.add_argument("--header", type=Path, default=root / "generated" / "score_data.h")
    parser.add_argument("--config-header", type=Path, default=root / "generated" / "artistic_config.h")
    parser.add_argument("--report", type=Path, default=root / "generated" / "score_report.md")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result, runtime, reactions = load_and_convert(args.translation_root.resolve())
        write_csv(result, args.csv.resolve())
        write_header(result, args.header.resolve())
        write_artistic_config(runtime, reactions, args.config_header.resolve())
        report = format_report(result)
        args.report.resolve().write_text(report, encoding="utf-8", newline="\n")
    except (OSError, KeyError, TypeError, yaml.YAMLError, ExportError) as exc:
        raise SystemExit(f"export failed: {exc}") from exc
    print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
