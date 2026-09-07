"""Narrow liveness monitoring and bounded recovery for live AudioSource streams."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import subprocess
import time

import numpy as np


class CaptureHealthState(str, Enum):
    HEALTHY = "healthy"
    SUSPECT = "suspect"
    UNHEALTHY = "unhealthy"
    RECOVERING = "recovering"
    VERIFYING = "verifying"


@dataclass(frozen=True)
class CaptureHealthConfig:
    enabled: bool = True
    unhealthy_window_seconds: float = 8.0
    recovery_verify_seconds: float = 3.0
    reboot_cooldown_seconds: float = 3600.0
    reboot_state_path: str = "/var/lib/bwm/whisper-audio-health.json"


@dataclass(frozen=True)
class FrameSignature:
    unique_samples: int
    minimum: int
    maximum: int
    sample_range: int
    standard_deviation: float
    pathological: bool


def frame_signature(samples) -> FrameSignature:
    """Recognise only the observed 0/-1 raw-int16 stuck-stream signature.

    This intentionally does not make a judgement from loudness, speech, or
    detector output.  Values are converted back to raw S16 units so the test
    remains tied to the signature observed from ``arecord``.
    """
    raw = np.rint(np.asarray(samples, dtype=np.float64) * 32768.0).astype(np.int64)
    if raw.size == 0:
        return FrameSignature(0, 0, 0, 0, 0.0, False)
    unique = np.unique(raw)
    minimum, maximum = int(unique[0]), int(unique[-1])
    deviation = float(np.std(raw))
    # All samples must be one of the two observed near-zero raw values.  The
    # cardinality/range/std checks make the condition explicit and auditable.
    pathological = (
        unique.size == 2
        and minimum >= -1
        and maximum <= 0
        and maximum - minimum <= 1
        and deviation <= 0.5
    )
    return FrameSignature(int(unique.size), minimum, maximum, maximum - minimum, deviation, pathological)


class CaptureHealthMonitor:
    """Pure frame-state machine; it has no dependency on detector decisions."""
    def __init__(self, config: CaptureHealthConfig, *, clock=time.monotonic):
        self.config, self._clock = config, clock
        self.reset()

    def reset(self):
        self.state = CaptureHealthState.HEALTHY
        self._pathological_since = None
        self._verify_started = None
        self._healthy_since = None
        self.pathological_frames = 0
        self.last_signature = None

    def begin_verification(self, now=None):
        now = self._clock() if now is None else now
        self.state = CaptureHealthState.VERIFYING
        self._verify_started, self._healthy_since = now, None
        self._pathological_since = None
        self.pathological_frames = 0

    def observe(self, samples, now=None):
        now = self._clock() if now is None else now
        signature = frame_signature(samples)
        self.last_signature = signature
        if self.state is CaptureHealthState.VERIFYING:
            if signature.pathological:
                self.pathological_frames += 1
                self._healthy_since = None
                if now - self._verify_started >= self.config.recovery_verify_seconds:
                    return "verification_failed"
                return None
            if self._healthy_since is None:
                self._healthy_since = now
            if now - self._healthy_since >= self.config.recovery_verify_seconds:
                self.reset()
                return "recovered"
            return None

        if not signature.pathological:
            self._pathological_since = None
            self.pathological_frames = 0
            self.state = CaptureHealthState.HEALTHY
            return None
        self.pathological_frames += 1
        if self._pathological_since is None:
            self._pathological_since = now
            self.state = CaptureHealthState.SUSPECT
            return None
        if now - self._pathological_since >= self.config.unhealthy_window_seconds:
            self.state = CaptureHealthState.UNHEALTHY
            return "unhealthy"
        return None


class RebootGuard:
    """Persist a wall-clock cooldown so a service restart cannot create a reboot loop."""
    def __init__(self, path, cooldown_seconds, *, wall_clock=time.time):
        self.path, self.cooldown_seconds, self._wall_clock = Path(path), cooldown_seconds, wall_clock

    def allowed(self):
        try:
            last = float(json.loads(self.path.read_text(encoding="utf-8")).get("last_reboot", 0))
        except (OSError, ValueError, json.JSONDecodeError):
            last = 0
        return self._wall_clock() - last >= self.cooldown_seconds

    def record(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"last_reboot": self._wall_clock()}), encoding="utf-8")


class CaptureHealthSupervisor:
    """AudioSource owner that performs one restart then optionally escalates.

    ``source_factory`` is deliberately the only source-specific dependency.
    Detector, capture/ASR, and messaging state are not consulted or restarted.
    """
    def __init__(self, source_factory, config: CaptureHealthConfig, *, emit=print,
                 clock=time.monotonic, reboot_guard=None, reboot=None, on_source_reopened=lambda: None):
        self.source_factory, self.config, self.emit = source_factory, config, emit
        self._clock = clock
        self.monitor = CaptureHealthMonitor(config, clock=clock)
        self.source = None
        self.active, self.recovery_attempted, self.reboot_requested = True, False, False
        self.reboot_guard = reboot_guard or RebootGuard(config.reboot_state_path, config.reboot_cooldown_seconds)
        self.reboot = reboot or (lambda: subprocess.Popen(["/bin/systemctl", "reboot"]))
        self.on_source_reopened = on_source_reopened

    def open(self):
        self.source = self.source_factory()
        self.source.open()
        self.monitor.reset()
        return self.source

    def set_active(self, active):
        if self.active != active:
            self.active = active
            self.monitor.reset()
            self.recovery_attempted = False
            self.reboot_requested = False

    def observe(self, samples, now=None):
        if not self.config.enabled or not self.active:
            return None
        event = self.monitor.observe(samples, now)
        if event == "unhealthy":
            signature = self.monitor.last_signature
            self.emit("[AudioHealth] pathological capture detected "
                      f"unique={signature.unique_samples} min={signature.minimum} max={signature.maximum} "
                      f"range={signature.sample_range} std={signature.standard_deviation:.3f} "
                      f"frames={self.monitor.pathological_frames}")
            self._restart(now)
        elif event == "recovered":
            # A full verification window closes this fault episode.  A later
            # independent fault may use its one bounded restart.
            self.recovery_attempted = False
            self.reboot_requested = False
            self.emit("[AudioHealth] capture recovered")
        elif event == "verification_failed":
            self.emit("[AudioHealth] recovery verification failed")
            self._escalate_reboot()
        return event

    def _restart(self, now=None):
        if self.recovery_attempted:
            return self._escalate_reboot()
        self.recovery_attempted = True
        self.monitor.state = CaptureHealthState.RECOVERING
        self.emit("[AudioHealth] restarting capture")
        try:
            if self.source:
                self.source.close()
            self.source = self.source_factory()
            self.source.open()
        except Exception as exc:
            self.emit(f"[AudioHealth] capture restart failed: {exc}")
            return self._escalate_reboot()
        self.on_source_reopened()
        self.monitor.begin_verification(self._clock() if now is None else now)
        self.emit("[AudioHealth] verifying recovery")

    def _escalate_reboot(self):
        if self.reboot_requested:
            return
        self.reboot_requested = True
        if self.reboot_guard.allowed():
            self.reboot_guard.record()
            self.emit("[AudioHealth] escalating to controlled reboot")
            self.reboot()
        else:
            self.emit("[AudioHealth] reboot escalation suppressed by cooldown")

    def close(self):
        if self.source:
            self.source.close()
            self.source = None
