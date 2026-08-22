"""Conservative, source-independent utterance capture from canonical frames."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Optional

import numpy as np


class CaptureState(str, Enum):
    IDLE = "idle"
    CAPTURING = "capturing"
    POST_ROLL = "post_roll"


@dataclass(frozen=True)
class CapturePolicy:
    pre_roll_seconds: float = 4.0
    end_silence_seconds: float = 1.5
    post_roll_seconds: float = 0.5
    max_utterance_seconds: float = 12.0

    def validate(self):
        if self.pre_roll_seconds < 0 or self.end_silence_seconds < 0 or self.post_roll_seconds < 0:
            raise ValueError("capture timing values must be non-negative")
        if self.max_utterance_seconds <= 0:
            raise ValueError("max_utterance_seconds must be positive")


@dataclass
class CompletedCapture:
    samples: np.ndarray
    sample_rate: int
    source_id: str
    detector_profile: str
    capture_index: int
    trigger_frame: int
    trigger_sample: int
    capture_start_frame: int
    capture_start_sample: int
    logical_end_frame: Optional[int]
    logical_end_sample: Optional[int]
    final_end_frame: int
    final_end_sample: int
    completion_reason: str
    pre_roll_requested_seconds: float
    pre_roll_available_seconds: float
    end_silence_seconds: float
    post_roll_seconds: float
    max_utterance_seconds: float
    ignored_trigger_count: int = 0

    def time(self, sample: Optional[int]) -> Optional[float]:
        return None if sample is None else sample / float(self.sample_rate)


class UtteranceCaptureController:
    """Capture sequential canonical frames from *real emitted* detector triggers.

    The caller owns detector evaluation and the shared ``AudioRingBuffer``.
    This class deliberately has no WAV, microphone, servo, or annotation knowledge.
    """

    def __init__(self, sample_rate, ring_buffer, policy=None, source_id="", detector_profile=""):
        self.sample_rate = int(sample_rate)
        self.ring_buffer = ring_buffer
        self.policy = policy or CapturePolicy()
        self.policy.validate()
        self.source_id = str(source_id)
        self.detector_profile = str(detector_profile)
        self.state = CaptureState.IDLE
        self._active = None
        self.completed = []
        self.ignored_trigger_count = 0

    @property
    def is_capturing(self):
        return self.state != CaptureState.IDLE

    def process_frame(self, frame, frame_index, emitted_trigger=False, temporal_candidate=False):
        """Consume one frame after it has been appended to the shared ring buffer.

        ``emitted_trigger`` must be the production trigger after cooldown/suppression;
        threshold crossings and comparison detector results are intentionally not inputs.
        """
        frame = np.asarray(frame, dtype=np.float32)
        if frame.ndim != 1:
            raise ValueError("UtteranceCaptureController expects mono 1-D frames")
        frame_end = (int(frame_index) + 1) * len(frame)

        started = False
        if emitted_trigger and not self.is_capturing:
            self._start(frame_index, frame_end, len(frame))
            started = True
        elif emitted_trigger:
            self.ignored_trigger_count += 1
            self._active["ignored_trigger_count"] += 1

        if not self.is_capturing:
            return None

        # The triggering frame is already in pre-roll, so never append it twice.
        if not started:
            self._active["parts"].append(frame.copy())
        self._active["final_end_frame"] = int(frame_index)
        self._active["final_end_sample"] = frame_end

        elapsed = frame_end - self._active["capture_start_sample"]
        if elapsed >= self._max_samples:
            return self._complete("max_duration")

        if self.state == CaptureState.CAPTURING:
            if temporal_candidate:
                self._active["negative_frames"] = 0
            else:
                self._active["negative_frames"] += 1
            if self._active["negative_frames"] >= self._end_negative_frames:
                self._active["logical_end_frame"] = int(frame_index)
                self._active["logical_end_sample"] = frame_end
                self.state = CaptureState.POST_ROLL
                if self.policy.post_roll_seconds == 0:
                    return self._complete("endpoint")
        elif self.state == CaptureState.POST_ROLL:
            post_roll = frame_end - self._active["logical_end_sample"]
            if post_roll >= self._post_roll_samples:
                return self._complete("endpoint")
        return None

    def finish(self):
        """Finish a still-active capture at a source boundary (for example WAV EOF)."""
        return self._complete("end_of_file") if self.is_capturing else None

    @property
    def _end_negative_frames(self):
        # Frames are canonical 30 ms but deriving this from sample rate/frame data
        # would require retaining a mutable frame-size assumption.  The trigger-time
        # frame size is stored on start; ceil keeps endpointing conservative.
        return max(1, math.ceil(self.policy.end_silence_seconds * self.sample_rate / self._active["frame_samples"]))

    @property
    def _post_roll_samples(self):
        return math.ceil(self.policy.post_roll_seconds * self.sample_rate)

    @property
    def _max_samples(self):
        return math.ceil(self.policy.max_utterance_seconds * self.sample_rate)

    def _start(self, frame_index, frame_end, frame_samples):
        pre_roll = self.ring_buffer.get_recent(self.policy.pre_roll_seconds).astype(np.float32, copy=True)
        available = len(pre_roll) / float(self.sample_rate)
        start_sample = frame_end - len(pre_roll)
        self._active = {
            "parts": [pre_roll], "trigger_frame": int(frame_index), "trigger_sample": frame_end,
            "capture_start_frame": max(0, start_sample // frame_samples),
            "capture_start_sample": start_sample, "logical_end_frame": None, "logical_end_sample": None,
            "final_end_frame": int(frame_index), "final_end_sample": frame_end,
            "negative_frames": 0, "frame_samples": frame_samples,
            "pre_roll_available_seconds": available, "ignored_trigger_count": 0,
        }
        self.state = CaptureState.CAPTURING

    def _complete(self, reason):
        active = self._active
        capture = CompletedCapture(
            samples=np.concatenate(active["parts"]).astype(np.float32, copy=False), sample_rate=self.sample_rate,
            source_id=self.source_id, detector_profile=self.detector_profile, capture_index=len(self.completed),
            trigger_frame=active["trigger_frame"], trigger_sample=active["trigger_sample"],
            capture_start_frame=active["capture_start_frame"], capture_start_sample=active["capture_start_sample"],
            logical_end_frame=active["logical_end_frame"], logical_end_sample=active["logical_end_sample"],
            final_end_frame=active["final_end_frame"], final_end_sample=active["final_end_sample"],
            completion_reason=reason, pre_roll_requested_seconds=self.policy.pre_roll_seconds,
            pre_roll_available_seconds=active["pre_roll_available_seconds"], end_silence_seconds=self.policy.end_silence_seconds,
            post_roll_seconds=self.policy.post_roll_seconds, max_utterance_seconds=self.policy.max_utterance_seconds,
            ignored_trigger_count=active["ignored_trigger_count"],
        )
        self.completed.append(capture)
        self._active = None
        self.state = CaptureState.IDLE
        return capture
