"""Last-resort runtime safety and observability at the hardware boundary."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import logging
import math


@dataclass(frozen=True)
class SafetyDecision:
    accepted: bool
    status: str
    target: str
    reason: str | None = None
    observed_value: float | None = None
    threshold: float | None = None


class RuntimeSafety:
    """Observe every hardware-bound event and reject only emergency outliers.

    The instance intentionally survives playback sessions: its history describes
    physical hardware use, rather than a logical score session.
    """

    def __init__(self, clock, dispatcher, config=None, logger=None):
        self._clock, self._dispatcher = clock, dispatcher
        self._config = config or {}
        self._logger = logger or logging.getLogger("runtime.safety")
        self._history = defaultdict(deque)
        self._requested_history = defaultdict(deque)
        # This is a deliberately dimensionless first-order heat-retention
        # heuristic, not a calibrated coil-temperature prediction.
        self._thermal = defaultdict(lambda: {"load": 0.0, "updated_at": None})
        self._metrics = defaultdict(lambda: {
            "requested_count": 0, "accepted_count": 0, "rejected_count": 0,
            "requested_duration": 0.0, "accepted_duration": 0.0,
            "last_requested_at": None, "last_accepted_at": None,
        })
        self.decisions = []

    def dispatch(self, event):
        """Account for and, if explicitly enabled, dispatch one runtime event."""
        now, target, duration = self._clock.now(), event.get("target"), float(event.get("duration", 0))
        metrics = self._metrics[target]
        metrics["requested_count"] += 1
        metrics["requested_duration"] += duration
        metrics["last_requested_at"] = now
        self._requested_history[target].append(now)
        thermal_load = self._thermal_load(target, now)
        emergency = self._config.get("emergency", {})
        decision, dispatched_event = self._decide(event, now, duration, emergency, thermal_load)
        self.decisions.append(decision)
        if decision.accepted:
            metrics["accepted_count"] += 1
            metrics["accepted_duration"] += float(dispatched_event.get("duration", 0))
            metrics["last_accepted_at"] = now
            self._history[target].append((now, float(dispatched_event.get("duration", 0))))
            self._add_thermal_load(target, float(dispatched_event.get("duration", 0)))
            self._dispatcher.dispatch(dispatched_event)
        else:
            metrics["rejected_count"] += 1
        if decision.status != "accepted":
            self._logger.warning("RuntimeSafety %s target=%s rule=%s observed=%s threshold=%s",
                                 decision.status, target, decision.reason,
                                 decision.observed_value, decision.threshold)
            print("[RuntimeSafety] %s target=%s rule=%s observed=%s threshold=%s" % (
                decision.status, target, decision.reason, decision.observed_value, decision.threshold))
        else:
            self._logger.debug("RuntimeSafety accepted target=%s duration=%s", target, duration)
        return decision

    def observations(self, target=None):
        """Return a small diagnostic snapshot; no background polling is needed."""
        now = self._clock.now()
        targets = [target] if target is not None else list(self._metrics)
        result = {}
        rate = self._config.get("emergency", {}).get("runaway_rate", {})
        window = float(rate.get("window_seconds", 5.0))
        for name in targets:
            metrics = dict(self._metrics[name])
            self._prune(name, now, window)
            history = self._history[name]
            requested = self._requested_history[name]
            while requested and requested[0] <= now - window:
                requested.popleft()
            metrics["recent_requested_count"] = len(requested)
            metrics["recent_requested_rate"] = len(requested) / window if window else 0.0
            metrics["recent_accepted_count"] = len(history)
            metrics["recent_accepted_rate"] = len(history) / window if window else 0.0
            metrics["rolling_active_seconds"] = sum(duration for _, duration in history)
            metrics["rolling_duty_fraction"] = metrics["rolling_active_seconds"] / window if window else 0.0
            self._thermal_load(name, now)
            thermal = self._thermal[name]
            metrics["thermal_load"] = thermal["load"]
            metrics["thermal_last_updated_at"] = thermal["updated_at"]
            result[name] = metrics
        return result.get(target) if target is not None else result

    def _decide(self, event, now, duration, emergency, thermal_load):
        target = event.get("target")
        enforcement_enabled = self._config.get("enabled", False)
        thermal = self._config.get("thermal", {})
        if not enforcement_enabled:
            return SafetyDecision(True, "accepted", target), event
        pulse = emergency.get("max_pulse_duration", {})
        if pulse.get("enabled", False) and duration > float(pulse["seconds"]):
            if pulse.get("action", "reject") == "clamp":
                adjusted = dict(event, duration=float(pulse["seconds"]))
                return SafetyDecision(True, "clamped", target, "max_pulse_duration", duration,
                                      float(pulse["seconds"])), adjusted
            return SafetyDecision(False, "rejected", target, "max_pulse_duration", duration,
                                  float(pulse["seconds"])), event
        rate = emergency.get("runaway_rate", {})
        if rate.get("enabled", False):
            window, maximum = float(rate["window_seconds"]), int(rate["max_events"])
            self._prune(target, now, window)
            observed = len(self._requested_history[target])
            if observed > maximum:
                return SafetyDecision(False, "rejected", target, "runaway_event_rate", observed,
                                      maximum), event
        duty = emergency.get("extreme_duty", {})
        if duty.get("enabled", False):
            window, maximum = float(duty["window_seconds"]), float(duty["max_fraction"])
            self._prune(target, now, window)
            observed = (sum(value for _, value in self._history[target]) + duration) / window
            if observed > maximum:
                return SafetyDecision(False, "rejected", target, "extreme_duty", observed, maximum), event
        if thermal.get("enabled", False) and thermal.get("enforce", False):
            reference = float(thermal["reference_pulse_seconds"])
            threshold = float(thermal["emergency_load_threshold"])
            observed = thermal_load + duration / reference
            if observed > threshold:
                return SafetyDecision(False, "rejected", target, "thermal_load", observed, threshold), event
        return SafetyDecision(True, "accepted", target), event

    def _thermal_load(self, target, now):
        """Decay one target's retained-load estimate using real monotonic time."""
        thermal = self._thermal[target]
        previous = thermal["updated_at"]
        if previous is not None:
            config = self._config.get("thermal", {})
            constant = float(config.get("cooling_time_constant_seconds", 90.0))
            if constant <= 0:
                raise ValueError("thermal cooling_time_constant_seconds must be positive")
            thermal["load"] *= math.exp(-(now - previous) / constant)
        thermal["updated_at"] = now
        return thermal["load"]

    def _add_thermal_load(self, target, duration):
        config = self._config.get("thermal", {})
        if not config.get("enabled", False):
            return
        reference = float(config.get("reference_pulse_seconds", 0.15))
        if reference <= 0:
            raise ValueError("thermal reference_pulse_seconds must be positive")
        self._thermal[target]["load"] += duration / reference

    def _prune(self, target, now, window):
        history = self._history[target]
        while history and history[0][0] <= now - window:
            history.popleft()
