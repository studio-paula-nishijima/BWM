"""Runtime-only score modulation between playback and hardware routing.

The scheduler in this module is deliberately limited to artistic timing.  It
does not make safety decisions; RuntimeSafety belongs downstream.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import heapq


class TimelinePolicy(str, Enum):
    OVERLAY = "overlay"
    OVERRIDE_WHILE_CONTINUING = "override_while_continuing"
    PAUSE_AND_FILL = "pause_and_fill"


@dataclass
class ModulationResult:
    immediate: list = field(default_factory=list)
    delayed: list = field(default_factory=list)  # (delay_seconds, runtime_event)
    pause_for: float = 0.0


def runtime_copy(event, **changes):
    """Copy an event before making it a runtime event; never mutate score data."""
    result = deepcopy(event)
    result.update(changes)
    result.setdefault("runtime", {}).setdefault("origin", "modulation")
    return result


class BaseTreatmentStrategy:
    """Small generic strategy interface used by named configurations."""

    def __init__(self, config):
        self.config = dict(config)
        self.policy = TimelinePolicy(self.config.get("timeline_policy", "overlay"))

    def applies_to(self, event):
        targets = self.config.get("targets")
        return not targets or event.get("target") in targets

    def process(self, event):
        raise NotImplementedError

    def _base_events(self, event):
        treatment = self.config.get("base_treatment", "preserve")
        if treatment == "suppress":
            return []
        if treatment == "replace":
            return [runtime_copy(item) for item in self.config.get("replacement_events", [])]
        return [runtime_copy(event)]


class CascadeStrategy(BaseTreatmentStrategy):
    def process(self, event):
        result = ModulationResult(immediate=self._base_events(event))
        delay = float(self.config.get("inter_step_delay", 0.0))
        duration = self.config.get("pulse_duration", event.get("duration"))
        for index, target in enumerate(self.config.get("ordered_targets", [])):
            generated = runtime_copy(event, target=target, duration=duration)
            generated["runtime"].update({"strategy": "cascade", "index": index})
            if index == 0:
                result.immediate.append(generated)
            else:
                result.delayed.append((index * delay, generated))
        if self.policy == TimelinePolicy.PAUSE_AND_FILL:
            result.pause_for = max(0.0, (len(self.config.get("ordered_targets", [])) - 1) * delay)
        return result


class MultiTapStrategy(BaseTreatmentStrategy):
    def process(self, event):
        result = ModulationResult(immediate=self._base_events(event))
        count = max(0, int(self.config.get("repeat_count", 1)))
        delay = float(self.config.get("inter_tap_delay", 0.0))
        duration = self.config.get("pulse_duration", event.get("duration"))
        for index in range(count):
            generated = runtime_copy(event, duration=duration)
            generated["runtime"].update({"strategy": "multi_tap", "index": index})
            if index == 0:
                result.immediate.append(generated)
            else:
                result.delayed.append((index * delay, generated))
        if self.policy == TimelinePolicy.PAUSE_AND_FILL:
            result.pause_for = max(0.0, (count - 1) * delay)
        return result


class SuppressStrategy(BaseTreatmentStrategy):
    def process(self, event):
        return ModulationResult()


class ReplaceStrategy(BaseTreatmentStrategy):
    def process(self, event):
        return ModulationResult(immediate=self._base_events(event))


class RuntimeModulationEngine:
    """Map a due base event to zero, one, or many scheduled runtime events."""

    _STRATEGIES = {
        "cascade": CascadeStrategy,
        "multi_tap": MultiTapStrategy,
        "suppress": SuppressStrategy,
        "replace": ReplaceStrategy,
    }

    def __init__(self, clock, dispatcher, playback_control=None):
        self._clock, self._dispatcher = clock, dispatcher
        self._playback_control = playback_control
        self._scheduled, self._sequence = [], 0
        self._active = None
        self._active_until = None
        self._resume_at = None
        self._cancelled = False

    @property
    def pending_count(self): return len(self._scheduled)

    @property
    def active_strategy(self): return self._active

    def bind_playback_control(self, playback_control):
        """Bind the narrow pause/resume capability after engine construction."""
        self._playback_control = playback_control

    def trigger(self, name, **config):
        """Arm an explicit, transport-independent strategy for due base events."""
        try:
            self._active = self._STRATEGIES[name](config)
        except KeyError as exc:
            raise ValueError("Unknown modulation strategy: %s" % name) from exc
        lifetime = config.get("active_for")
        self._active_until = None if lifetime is None else self._clock.now() + float(lifetime)
        return self._active

    def process(self, base_event):
        if self._cancelled:
            return []
        self._expire_active()
        if self._active is None or not self._active.applies_to(base_event):
            events = [runtime_copy(base_event, runtime={"origin": "base"})]
        else:
            result = self._active.process(base_event)
            events = result.immediate
            for delay, event in result.delayed:
                self._schedule(delay, event)
            if result.pause_for:
                self._pause_for(result.pause_for)
            # An overlay reaction with no explicit lifetime is a one-shot transform.
            if self._active.policy != TimelinePolicy.OVERRIDE_WHILE_CONTINUING or self._active_until is None:
                self._active = None
                self._active_until = None
        self._dispatch_all(events)
        return events

    def step(self):
        """Dispatch due delayed runtime events and resume a completed fill."""
        if self._cancelled:
            return 0
        now = self._clock.now()
        emitted = 0
        while self._scheduled and self._scheduled[0][0] <= now:
            _, _, event = heapq.heappop(self._scheduled)
            self._dispatch_all([event])
            emitted += 1
        if self._resume_at is not None and now >= self._resume_at:
            self._playback_control.resume()
            self._resume_at = None
        self._expire_active()
        return emitted

    def cancel(self):
        self._scheduled.clear()
        self._active = self._active_until = None
        self._cancelled = True
        if self._resume_at is not None and self._playback_control is not None:
            self._playback_control.resume()
        self._resume_at = None

    def _schedule(self, delay, event):
        self._sequence += 1
        heapq.heappush(self._scheduled, (self._clock.now() + max(0.0, delay), self._sequence, event))

    def _pause_for(self, duration):
        if self._playback_control is None:
            raise RuntimeError("PAUSE_AND_FILL requires playback control")
        self._playback_control.pause()
        self._resume_at = self._clock.now() + duration

    def _expire_active(self):
        if self._active_until is not None and self._clock.now() >= self._active_until:
            self._active = self._active_until = None

    def _dispatch_all(self, events):
        for event in events:
            self._dispatcher.dispatch(event)
