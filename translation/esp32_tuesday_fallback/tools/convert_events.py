#!/usr/bin/env python3
"""Validate the canonical Translation score and emit the Tuesday fallback table."""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np


CONVERTER_VERSION = "1"
MAX_PULSE_MS = 500
MIN_OFF_MS = 100
TARGET_TO_CHANNEL = {f"solenoid_{index}": index - 1 for index in range(1, 7)}
REQUIRED_FIELDS = {
    "playback_time",
    "timestamp",
    "type",
    "target",
    "action",
    "duration",
    "metadata",
}
UINT32_MAX = (1 << 32) - 1
UINT16_MAX = (1 << 16) - 1
UINT8_MAX = (1 << 8) - 1


class ConversionError(ValueError):
    """Raised when score data cannot safely be converted."""


@dataclass(frozen=True)
class ConvertedEvent:
    time_ms: int
    duration_ms: int
    channel: int


@dataclass(frozen=True)
class ConversionResult:
    source_path: Path
    source_sha256: str
    array_shape: tuple[int, ...]
    event_type_name: str
    raw_events: tuple[dict[str, Any], ...]
    events: tuple[ConvertedEvent, ...]
    first_playback_time: float
    playback_min: float
    playback_max: float
    duration_min: float
    duration_max: float
    event_types: frozenset[str]
    targets: frozenset[str]
    actions: frozenset[str]
    per_target_counts: dict[str, int]
    min_same_channel_interval_seconds: float | None
    max_same_channel_rate_hz: float | None
    min_quantized_off_ms: int | None
    minimum_off_violations: int
    max_time_quantization_error_ms: float
    max_duration_quantization_error_ms: float


def _number(value: Any, label: str, index: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ConversionError(f"event {index}: {label} must be numeric, got {type(value).__name__}")
    converted = float(value)
    if not math.isfinite(converted):
        raise ConversionError(f"event {index}: {label} must be finite, got {value!r}")
    return converted


def _round_ms(seconds: float) -> int:
    """Round a non-negative seconds value to nearest millisecond, half up."""
    return int(math.floor(seconds * 1000.0 + 0.5))


def _validate_record(record: Any, index: int) -> tuple[dict[str, Any], float, float, int]:
    if not isinstance(record, dict):
        raise ConversionError(f"event {index}: expected dict, got {type(record).__name__}")
    missing = REQUIRED_FIELDS - record.keys()
    if missing:
        raise ConversionError(f"event {index}: missing required fields {sorted(missing)}")
    if record["type"] != "solenoid":
        raise ConversionError(f"event {index}: unsupported type {record['type']!r}")
    if record["action"] != "pulse":
        raise ConversionError(f"event {index}: unsupported action {record['action']!r}")
    target = record["target"]
    if target not in TARGET_TO_CHANNEL:
        raise ConversionError(f"event {index}: unsupported target {target!r}")
    playback_time = _number(record["playback_time"], "playback_time", index)
    if playback_time < 0:
        raise ConversionError(f"event {index}: playback_time must be non-negative")
    duration = _number(record["duration"], "duration", index)
    if duration <= 0:
        raise ConversionError(f"event {index}: duration must be positive")
    duration_ms = _round_ms(duration)
    if duration_ms <= 0:
        raise ConversionError(f"event {index}: duration rounds to zero milliseconds")
    if duration_ms > MAX_PULSE_MS:
        raise ConversionError(
            f"event {index}: {duration_ms} ms pulse exceeds {MAX_PULSE_MS} ms hard maximum"
        )
    return record, playback_time, duration, TARGET_TO_CHANNEL[target]


def convert_array(array: np.ndarray, source_path: Path, source_sha256: str) -> ConversionResult:
    if not isinstance(array, np.ndarray):
        raise ConversionError(f"expected NumPy ndarray, got {type(array).__name__}")
    if array.ndim != 1:
        raise ConversionError(f"expected one-dimensional object array, got shape {array.shape}")
    if array.size == 0:
        raise ConversionError("score contains no events")

    validated = [_validate_record(record, index) for index, record in enumerate(array.tolist())]
    validated.sort(key=lambda item: item[1])
    first_playback_time = validated[0][1]

    converted: list[ConvertedEvent] = []
    time_errors: list[float] = []
    duration_errors: list[float] = []
    raw_events: list[dict[str, Any]] = []
    for index, (record, playback_time, duration, channel) in enumerate(validated):
        rebased = playback_time - first_playback_time
        if not math.isfinite(rebased) or rebased < 0:
            raise ConversionError(f"event {index}: invalid rebased playback time {rebased!r}")
        time_ms = _round_ms(rebased)
        duration_ms = _round_ms(duration)
        if time_ms > UINT32_MAX:
            raise ConversionError(f"event {index}: time_ms overflows uint32_t")
        if duration_ms > UINT16_MAX:
            raise ConversionError(f"event {index}: duration_ms overflows uint16_t")
        if channel > UINT8_MAX:
            raise ConversionError(f"event {index}: channel overflows uint8_t")
        converted.append(ConvertedEvent(time_ms, duration_ms, channel))
        raw_events.append(record)
        time_errors.append(abs(time_ms - rebased * 1000.0))
        duration_errors.append(abs(duration_ms - duration * 1000.0))

    if any(left.time_ms > right.time_ms for left, right in zip(converted, converted[1:])):
        raise ConversionError("generated events are not monotonic after sorting")

    per_channel: dict[int, list[ConvertedEvent]] = defaultdict(list)
    raw_per_channel: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for event, (_, playback_time, duration, channel) in zip(converted, validated):
        per_channel[channel].append(event)
        raw_per_channel[channel].append((playback_time, duration))

    raw_intervals = [
        current[0] - previous[0]
        for events in raw_per_channel.values()
        for previous, current in zip(events, events[1:])
    ]
    quantized_off_intervals = [
        current.time_ms - (previous.time_ms + previous.duration_ms)
        for events in per_channel.values()
        for previous, current in zip(events, events[1:])
    ]
    minimum_off_violations = sum(value < MIN_OFF_MS for value in quantized_off_intervals)
    min_interval = min(raw_intervals, default=None)

    raw_tuple = tuple(raw_events)
    return ConversionResult(
        source_path=source_path,
        source_sha256=source_sha256,
        array_shape=tuple(array.shape),
        event_type_name=type(raw_tuple[0]).__name__,
        raw_events=raw_tuple,
        events=tuple(converted),
        first_playback_time=first_playback_time,
        playback_min=min(item[1] for item in validated),
        playback_max=max(item[1] for item in validated),
        duration_min=min(item[2] for item in validated),
        duration_max=max(item[2] for item in validated),
        event_types=frozenset(str(item[0]["type"]) for item in validated),
        targets=frozenset(str(item[0]["target"]) for item in validated),
        actions=frozenset(str(item[0]["action"]) for item in validated),
        per_target_counts=dict(sorted(Counter(str(item[0]["target"]) for item in validated).items())),
        min_same_channel_interval_seconds=min_interval,
        max_same_channel_rate_hz=(1.0 / min_interval) if min_interval else None,
        min_quantized_off_ms=min(quantized_off_intervals, default=None),
        minimum_off_violations=minimum_off_violations,
        max_time_quantization_error_ms=max(time_errors),
        max_duration_quantization_error_ms=max(duration_errors),
    )


def load_and_convert(source_path: Path) -> ConversionResult:
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise ConversionError(f"cannot read {source_path}: {exc}") from exc
    try:
        array = np.load(source_path, allow_pickle=True)
    except Exception as exc:
        raise ConversionError(f"cannot load NumPy score {source_path}: {exc}") from exc
    return convert_array(array, source_path, hashlib.sha256(source_bytes).hexdigest())


def _provenance_lines(result: ConversionResult) -> list[str]:
    return [
        "Generated from translation/events.npy; do not hand-edit.",
        f"Source SHA-256: {result.source_sha256}",
        f"Converter version: {CONVERTER_VERSION}",
    ]


def write_csv(result: ConversionResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        for line in _provenance_lines(result):
            handle.write(f"# {line}\n")
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("time_ms", "channel", "duration_ms"))
        for event in result.events:
            writer.writerow((event.time_ms, event.channel, event.duration_ms))


def write_header(result: ConversionResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"    {{{event.time_ms}u, {event.duration_ms}u, {event.channel}u}},"
        for event in result.events
    )
    score_duration_ms = result.events[-1].time_ms
    provenance = "\n".join(f"// {line}" for line in _provenance_lines(result))
    content = f"""#pragma once

{provenance}

#include <cstddef>
#include <cstdint>

namespace bwm_tuesday {{

struct ScoreEvent {{
  uint32_t time_ms;
  uint16_t duration_ms;
  uint8_t channel;
}};

static_assert(sizeof(ScoreEvent) == 8, "unexpected ScoreEvent layout");

constexpr ScoreEvent kScoreEvents[] = {{
{rows}
}};

constexpr size_t kScoreEventCount = sizeof(kScoreEvents) / sizeof(kScoreEvents[0]);
constexpr uint32_t kScoreDurationMs = {score_duration_ms}u;
constexpr char kScoreSourceSha256[] = "{result.source_sha256}";

}}  // namespace bwm_tuesday
"""
    output_path.write_text(content, encoding="utf-8", newline="\n")


def _format_records(records: Iterable[dict[str, Any]]) -> str:
    return "\n".join(f"  {record!r}" for record in records)


def format_report(result: ConversionResult) -> str:
    score_duration_ms = result.events[-1].time_ms
    lines = [
        "BWM Tuesday fallback score report",
        f"source: translation/events.npy",
        f"source SHA-256: {result.source_sha256}",
        f"array shape: {result.array_shape}",
        f"event count: {len(result.events)}",
        f"event Python type: {result.event_type_name}",
        f"event fields: {sorted(result.raw_events[0].keys())}",
        f"event types: {sorted(result.event_types)}",
        f"targets: {sorted(result.targets)}",
        f"actions: {sorted(result.actions)}",
        "first five events:",
        _format_records(result.raw_events[:5]),
        "last five events:",
        _format_records(result.raw_events[-5:]),
        f"playback time range: {result.playback_min:.9f}..{result.playback_max:.9f} s",
        f"rebased score duration: {score_duration_ms} ms ({score_duration_ms / 1000.0:.3f} s)",
        f"pulse duration range: {result.duration_min * 1000.0:.3f}..{result.duration_max * 1000.0:.3f} ms",
        f"per-target event counts: {result.per_target_counts}",
        f"minimum same-channel start interval: {result.min_same_channel_interval_seconds:.9f} s",
        f"maximum observed same-channel event rate: {result.max_same_channel_rate_hz:.6f} Hz",
        f"minimum quantized same-channel OFF interval: {result.min_quantized_off_ms} ms",
        f"{MIN_OFF_MS} ms minimum-OFF violations: {result.minimum_off_violations}",
        f"maximum time quantization error: {result.max_time_quantization_error_ms:.6f} ms",
        f"maximum duration quantization error: {result.max_duration_quantization_error_ms:.6f} ms",
        "malformed/unexpected records: 0",
    ]
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    fallback_root = Path(__file__).resolve().parents[1]
    translation_root = fallback_root.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=translation_root / "events.npy")
    parser.add_argument("--csv", type=Path, default=fallback_root / "generated" / "events.csv")
    parser.add_argument("--header", type=Path, default=fallback_root / "generated" / "score_data.h")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = load_and_convert(args.input.resolve())
        if result.minimum_off_violations:
            raise ConversionError(
                f"canonical score violates {MIN_OFF_MS} ms minimum OFF interval "
                f"{result.minimum_off_violations} time(s)"
            )
        write_csv(result, args.csv.resolve())
        write_header(result, args.header.resolve())
    except ConversionError as exc:
        raise SystemExit(f"conversion failed: {exc}") from exc
    print(format_report(result))
    print(f"wrote CSV: {args.csv.resolve()}")
    print(f"wrote header: {args.header.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
