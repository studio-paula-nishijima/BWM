#!/usr/bin/env python3
"""Exercise the complete embedded score and every reaction through full-controller guards."""

from __future__ import annotations

import csv
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import yaml

MAX_PULSE_MS = 500
MIN_OFF_MS = 40
WINDOW_MS = 10_000
MAX_EVENTS = 160
MAX_DUTY_MS = 9_000


@dataclass(frozen=True)
class Pulse:
    at: int
    duration: int
    channel: int


def load_score(path: Path) -> list[Pulse]:
    with path.open(encoding="utf-8") as handle:
        rows = (line for line in handle if not line.startswith("#"))
        return [Pulse(int(row["time_ms"]), int(row["duration_ms"]), int(row["channel"]))
                for row in csv.DictReader(rows)]


def serialize_channels(pulses: list[Pulse]) -> list[Pulse]:
    free = [0] * 6
    result = []
    for pulse in sorted(pulses, key=lambda item: item.at):
        at = max(pulse.at, free[pulse.channel] + MIN_OFF_MS if free[pulse.channel] else pulse.at)
        result.append(Pulse(at, pulse.duration, pulse.channel))
        free[pulse.channel] = at + pulse.duration
    return sorted(result, key=lambda item: item.at)


def emergency_rejections(pulses: list[Pulse]) -> dict[str, int]:
    history = defaultdict(deque)
    rejected = defaultdict(int)
    for pulse in pulses:
        if pulse.channel not in range(6):
            rejected["channel"] += 1; continue
        if not 0 < pulse.duration <= MAX_PULSE_MS:
            rejected["duration"] += 1; continue
        items = history[pulse.channel]
        while items and pulse.at - items[0].at >= WINDOW_MS:
            items.popleft()
        if len(items) >= MAX_EVENTS:
            rejected["rate"] += 1; continue
        if sum(item.duration for item in items) + pulse.duration > MAX_DUTY_MS:
            rejected["duty"] += 1; continue
        if items and pulse.at - (items[-1].at + items[-1].duration) < MIN_OFF_MS:
            rejected["minimum_off"] += 1; continue
        items.append(pulse)
    return dict(rejected)


def apply_reaction(score: list[Pulse], name: str, config: dict) -> list[Pulse]:
    """Run a named reaction repeatedly across the whole score when its busy window permits."""
    output = []
    next_trigger = 0
    index = 0
    while index < len(score):
        trigger = score[index].at
        if trigger < next_trigger:
            output.append(score[index]); index += 1; continue
        quiet_start = trigger + round(float(config.get("initial_quiet_gap_seconds", 0)) * 1000)
        if config["type"] == "override_sequence":
            offset = quiet_start
            generated = []
            for phase in config["phases"]:
                if phase["type"] == "wait":
                    offset += round(float(phase["duration_seconds"]) * 1000)
                    continue
                targets = list(range(6)) if phase["targets"] == "all" else [int(v.split("_")[-1]) - 1 for v in phase["targets"]]
                spacing = round(float(phase.get("spacing_seconds", 0)) * 1000)
                generated += [Pulse(offset + (i * spacing if phase["type"] == "sequence" else 0), 150, target)
                              for i, target in enumerate(targets)]
                if phase["type"] == "sequence": offset += max(0, len(targets) - 1) * spacing
            next_trigger = offset
            while index < len(score) and score[index].at < next_trigger:
                index += 1
            output.extend(generated)
        else:
            window = round(float(config["duration_seconds"]) * 1000)
            count = int(config["repeat_count"])
            spacing = round(float(config["tap_spacing_seconds"]) * 1000)
            next_trigger = trigger + window
            while index < len(score) and score[index].at < next_trigger:
                event = score[index]
                output.extend(Pulse(event.at + tap * spacing, event.duration, event.channel) for tap in range(count))
                index += 1
    return serialize_channels(output)


def run(root: Path) -> str:
    score = load_score(root / "generated" / "events.csv")
    reactions = yaml.safe_load((root.parent / "configs" / "voice_reactions.yaml").read_text(encoding="utf-8"))["strategies"]
    rows = [("base_score", len(score), emergency_rejections(serialize_channels(score)))]
    for name, config in reactions.items():
        pulses = apply_reaction(score, name, config)
        rows.append((name, len(pulses), emergency_rejections(pulses)))
    lines = ["# Full-controller safety simulation", "",
             f"Complete filtered score events: {len(score)}", "",
             "| Scenario | Admitted artistic pulses | Emergency guard rejections |",
             "|---|---:|---:|"]
    for name, count, rejected in rows:
        lines.append(f"| `{name}` | {count} | {sum(rejected.values())} |")
    lines += ["", f"Constants: max pulse {MAX_PULSE_MS} ms; minimum OFF {MIN_OFF_MS} ms; "
                      f"{MAX_EVENTS} events and {MAX_DUTY_MS} ms ON per channel per {WINDOW_MS} ms window.",
              "Per-channel work is serialized like the current Pi GPIO backend; this preserves every admitted tap while bounding storage.", ""]
    if any(rejected for _, _, rejected in rows):
        raise RuntimeError(f"emergency safety rejected artistic work: {rows!r}")
    return "\n".join(lines)


if __name__ == "__main__":
    project = Path(__file__).resolve().parents[1]
    report = run(project)
    output = project / "generated" / "safety_report.md"
    output.write_text(report, encoding="utf-8", newline="\n")
    print(report)
