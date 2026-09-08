"""Read-only playback timeline for runoff-derived Halo activity."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


def mean_runoff_activity(channel_values):
    """Return the arithmetic mean of aligned normalized/shaped channels."""
    arrays = [np.asarray(values, dtype=float) for values in channel_values.values()]
    if not arrays:
        raise ValueError("runoff activity requires at least one channel")
    shape = arrays[0].shape
    if any(values.shape != shape for values in arrays):
        raise ValueError("runoff control channels must have aligned shapes")
    stacked = np.stack(arrays)
    if not np.all(np.isfinite(stacked)) or np.any((stacked < 0) | (stacked > 1)):
        raise ValueError("runoff control values must be finite and within [0, 1]")
    return np.mean(stacked, axis=0)


@dataclass(frozen=True)
class RunoffActivityTimeline:
    """Mean runoff state indexed by the immutable score's playback clock."""

    playback_times: np.ndarray
    activity: np.ndarray
    timestamps: np.ndarray
    channel_names: tuple[str, ...]

    def __post_init__(self):
        times = np.asarray(self.playback_times, dtype=float)
        activity = np.asarray(self.activity, dtype=float)
        timestamps = np.asarray(self.timestamps)
        if not self.channel_names:
            raise ValueError("runoff timeline requires channel names")
        if times.ndim != 1 or activity.shape != times.shape or timestamps.shape != times.shape:
            raise ValueError("runoff timeline arrays must be aligned one-dimensional values")
        if len(times) == 0 or np.any(np.diff(times) <= 0):
            raise ValueError("runoff playback times must be non-empty and strictly increasing")
        if not np.all(np.isfinite(activity)) or np.any((activity < 0) | (activity > 1)):
            raise ValueError("runoff activity must be finite and within [0, 1]")
        object.__setattr__(self, "playback_times", times)
        object.__setattr__(self, "activity", activity)
        object.__setattr__(self, "timestamps", timestamps)

    @classmethod
    def from_channels(cls, channels):
        """Build from aligned scheduler inputs after normalization and shaping."""
        if not channels:
            raise ValueError("runoff timeline requires channel data")
        names = tuple(channels)
        first = channels[names[0]]
        times = np.asarray(first["playback_times"], dtype=float)
        timestamps = np.asarray(first["timestamps"])
        for name in names[1:]:
            item = channels[name]
            if not np.array_equal(np.asarray(item["playback_times"], dtype=float), times):
                raise ValueError("runoff channels must share playback times")
            if not np.array_equal(np.asarray(item["timestamps"]), timestamps):
                raise ValueError("runoff channels must share timestamps")
        activity = mean_runoff_activity({name: channels[name]["values"] for name in names})
        return cls(times, activity, timestamps, names)

    def activity_at(self, playback_time):
        """Return the current piecewise-constant control state at score time."""
        index = int(np.searchsorted(self.playback_times, float(playback_time), side="right") - 1)
        index = min(max(index, 0), len(self.activity) - 1)
        return float(self.activity[index])

    def save(self, path):
        np.savez_compressed(
            Path(path), schema_version=np.array(1, dtype=np.int64),
            playback_times=self.playback_times, activity=self.activity,
            timestamps=self.timestamps, channel_names=np.asarray(self.channel_names),
        )

    @classmethod
    def load(cls, path):
        with np.load(Path(path), allow_pickle=False) as data:
            if int(data["schema_version"]) != 1:
                raise ValueError("unsupported runoff timeline schema")
            return cls(data["playback_times"], data["activity"], data["timestamps"],
                       tuple(str(name) for name in data["channel_names"]))


@dataclass(frozen=True)
class SessionRunoffActivity:
    """Read-only view rebased to one prepared playback session."""

    timeline: RunoffActivityTimeline
    source_playback_origin: float

    def activity_at(self, session_playback_time):
        return self.timeline.activity_at(self.source_playback_origin + float(session_playback_time))
