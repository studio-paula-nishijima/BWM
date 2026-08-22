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
        self._external_pending, self._external_resume_at, self._external_busy_until = 0, None, None
        self._active = None
        self._active_until = None
        self._resume_at = None
        self._cancelled = False

    @property
    def pending_count(self): return len(self._scheduled)

    @property
    def active_strategy(self): return self._active

    @property
    def external_busy(self):
        return (self._external_pending > 0 or self._external_resume_at is not None
                or (self._external_busy_until is not None and self._clock.now() < self._external_busy_until))

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

    def trigger_external(self, name, event, **config):
        """Start one configured external reaction without changing score time."""
        if self._cancelled:
            return False
        if name == "override_sequence":
            return self._trigger_external_sequence(event, config)
        if name == "repeat_transform":
            return self._trigger_repeat_transform(config)
        try:
            strategy = self._STRATEGIES[name](config)
        except KeyError as exc:
            raise ValueError("Unknown modulation strategy: %s" % name) from exc
        lifetime = config.get("duration_seconds")
        if lifetime is not None:
            # A temporary transform handles only due base events in its window.
            self._active, self._active_until = strategy, self._clock.now() + float(lifetime)
            self._external_busy_until = self._active_until
            return True
        result = strategy.process(event)
        for delay, delayed_event in result.delayed:
            self._schedule(delay, delayed_event, external=True)
        if result.pause_for:
            self._pause_for(result.pause_for, external=True)
        self._dispatch_all(result.immediate)
        return self.external_busy

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
            if (self._active.policy != TimelinePolicy.OVERRIDE_WHILE_CONTINUING
                    and self._active_until is None):
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
            _, _, external, event = heapq.heappop(self._scheduled)
            self._dispatch_all([event])
            if external:
                self._external_pending -= 1
            emitted += 1
        if self._resume_at is not None and now >= self._resume_at:
            self._playback_control.resume()
            self._resume_at = None
        if self._external_resume_at is not None and now >= self._external_resume_at:
            self._external_resume_at = None
        self._expire_active()
        return emitted

    def cancel(self):
        self._scheduled.clear()
        self._external_pending = 0
        self._external_busy_until = None
        self._active = self._active_until = None
        self._cancelled = True
        if self._resume_at is not None and self._playback_control is not None:
            self._playback_control.resume()
        self._resume_at = self._external_resume_at = None

    def _trigger_external_sequence(self, event, config):
        quiet_gap = float(config.get("initial_quiet_gap_seconds", 0.0))
        last_admitted = getattr(self._dispatcher, "last_accepted_at", None)
        start_delay = quiet_gap if last_admitted is None else max(0.0, quiet_gap - (self._clock.now() - last_admitted))
        duration = config.get("pulse_duration", event.get("duration"))
        offset = start_delay
        for phase in config["phases"]:
            if phase["type"] == "wait":
                offset += float(phase["duration_seconds"])
                continue
            spacing = float(phase.get("spacing_seconds", 0.0))
            for index, target in enumerate(phase["targets"]):
                generated = runtime_copy(event, target=target, duration=duration)
                generated["runtime"].update({"strategy": "override_sequence", "phase": phase["type"], "index": index})
                self._schedule(offset + (index * spacing if phase["type"] == "sequence" else 0.0),
                               generated, external=True)
            if phase["type"] == "sequence":
                offset += max(0, len(phase["targets"]) - 1) * spacing
        self._external_busy_until = self._clock.now() + offset
        # Suppress due base events while logical score time continues.
        self._active = SuppressStrategy({"timeline_policy": "override_while_continuing", "base_treatment": "suppress"})
        self._active_until = self._external_busy_until
        # A zero quiet gap is genuinely immediate rather than waiting for the
        # next playback-loop iteration.
        self.step()
        return True

    def _trigger_repeat_transform(self, config):
        strategy = MultiTapStrategy({"timeline_policy": "overlay", "base_treatment": "suppress",
                                     "repeat_count": config["repeat_count"],
                                     "inter_tap_delay": config["tap_spacing_seconds"]})
        self._active, self._active_until = strategy, self._clock.now() + float(config["duration_seconds"])
        self._external_busy_until = self._active_until
        return True

    def _schedule(self, delay, event, external=False):
        self._sequence += 1
        heapq.heappush(self._scheduled, (self._clock.now() + max(0.0, delay), self._sequence, external, event))
        if external:
            self._external_pending += 1

    def _pause_for(self, duration, external=False):
        if self._playback_control is None:
            raise RuntimeError("PAUSE_AND_FILL requires playback control")
        self._playback_control.pause()
        resume_at = self._clock.now() + duration
        self._resume_at = resume_at
        if external:
            self._external_resume_at = resume_at

    def _expire_active(self):
        if self._active_until is not None and self._clock.now() >= self._active_until:
            self._active = self._active_until = None

    def _dispatch_all(self, events):
        for event in events:
            self._dispatcher.dispatch(event)
