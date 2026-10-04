from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("convert_events", ROOT / "tools" / "convert_events.py")
assert SPEC and SPEC.loader
convert_events = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = convert_events
SPEC.loader.exec_module(convert_events)


def event(
    target: str = "solenoid_1",
    playback_time: float = 2.0,
    duration: float = 0.15,
    event_type: str = "solenoid",
    action: str = "pulse",
) -> dict:
    return {
        "playback_time": playback_time,
        "timestamp": "2000-01-01T00:00:00.000000",
        "type": event_type,
        "target": target,
        "action": action,
        "duration": duration,
        "metadata": {"frequency": 1.0, "source_value": 0.5},
    }


def convert(records: list[dict]):
    return convert_events.convert_array(np.array(records, dtype=object), Path("events.npy"), "0" * 64)


def test_all_six_target_mappings() -> None:
    result = convert([event(f"solenoid_{index}", float(index)) for index in range(1, 7)])
    assert [item.channel for item in result.events] == list(range(6))


def test_current_canonical_score_converts() -> None:
    result = convert_events.load_and_convert(ROOT.parent / "events.npy")
    assert len(result.events) == 6253
    assert result.targets == frozenset(convert_events.TARGET_TO_CHANNEL)
    assert result.minimum_off_violations == 0


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (event(target="solenoid_7"), "unsupported target"),
        (event(event_type="halo"), "unsupported type"),
        (event(action="on"), "unsupported action"),
        (event(playback_time=-0.1), "non-negative"),
        (event(playback_time=float("nan")), "finite"),
        (event(duration=0), "positive"),
        (event(duration=-0.1), "positive"),
        (event(duration=0.501), "hard maximum"),
    ],
)
def test_invalid_records_are_rejected(record: dict, message: str) -> None:
    with pytest.raises(convert_events.ConversionError, match=message):
        convert([record])


def test_events_are_stably_sorted_and_rebased() -> None:
    result = convert([event("solenoid_2", 3.0), event("solenoid_1", 1.25)])
    assert result.events == (
        convert_events.ConvertedEvent(0, 150, 0),
        convert_events.ConvertedEvent(1750, 150, 1),
    )


def test_millisecond_quantization_is_deterministic_half_up() -> None:
    result = convert([event(playback_time=1.0), event(playback_time=1.0015, duration=0.1505)])
    assert result.events[1].time_ms == 2
    assert result.events[1].duration_ms == 151


def test_generated_header_count_matches_csv(tmp_path: Path) -> None:
    result = convert([event("solenoid_1", 1.0), event("solenoid_2", 2.0)])
    csv_path = tmp_path / "events.csv"
    header_path = tmp_path / "score_data.h"
    convert_events.write_csv(result, csv_path)
    convert_events.write_header(result, header_path)
    csv_lines = [line for line in csv_path.read_text(encoding="utf-8").splitlines() if not line.startswith("#")]
    rows = list(csv.DictReader(csv_lines))
    assert len(rows) == len(result.events)
    assert f"kScoreEventCount = sizeof(kScoreEvents) / sizeof(kScoreEvents[0])" in header_path.read_text(
        encoding="utf-8"
    )


def test_minimum_off_analysis_detects_violation() -> None:
    result = convert([event(playback_time=1.0), event(playback_time=1.2)])
    assert result.min_quantized_off_ms == 50
    assert result.minimum_off_violations == 1
