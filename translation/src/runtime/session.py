"""Persistent activation runtime with wall-clock bounded playback sessions."""

import threading

from runtime.modulation import RuntimeModulationEngine
from runtime.playback import PlaybackEngine
from runtime.reaction_policy import ReactionPolicy
from runtime.safety import RuntimeSafety


class PlaybackSessionRuntime:
    """Keep an installation runtime alive while creating clean sessions on activation."""

    def __init__(self, events_factory, clock, dispatcher, session_timeout, initially_active=False,
                 event_logger=None, safety_config=None, reaction_policy_config=None, rng=None):
        self._events_factory, self._clock, self._dispatcher = events_factory, clock, dispatcher
        self._session_timeout, self._event_logger = float(session_timeout), event_logger
        self._safety = RuntimeSafety(clock, dispatcher, safety_config)
        self._reaction_policy = None if reaction_policy_config is None else ReactionPolicy(
            reaction_policy_config.get("strategies", {}), reaction_policy_config.get("policies", {}), rng)
        self._changed = threading.Condition()
        self._active = False
        self._engine = self._modulation = self._started_at = None
        if initially_active:
            self.activate()

    @property
    def is_active(self):
        with self._changed:
            return self._active

    @property
    def engine(self): return self._engine

    @property
    def modulation(self): return self._modulation

    @property
    def safety(self): return self._safety

    def activate(self):
        with self._changed:
            if self._active:
                return False
            begin_session = getattr(self._dispatcher, "begin_session", None)
            if begin_session is not None:
                begin_session()
            modulation = RuntimeModulationEngine(self._clock, self._safety)
            engine = PlaybackEngine(self._events_factory(), self._clock,
                                    due_event_handler=modulation.process,
                                    event_logger=self._event_logger)
            modulation.bind_playback_control(engine)
            engine.start()
            self._engine, self._modulation = engine, modulation
            self._started_at, self._active = self._clock.now(), True
            print("[Session] ACTIVE: fresh playback session started")
            self._changed.notify_all()
            return True

    def deactivate(self):
        """Explicit cancellation, not a logical-score pause."""
        with self._changed:
            if not self._active:
                return False
            self._finish_session("cancelled")
            self._changed.notify_all()
            return True

    cancel = deactivate

    def toggle(self):
        return self.deactivate() if self.is_active else self.activate()

    def trigger(self, name, **config):
        with self._changed:
            if not self._active:
                raise RuntimeError("Cannot trigger modulation while idle")
            return self._modulation.trigger(name, **config)

    def trigger_reaction(self, category="default"):
        with self._changed:
            if not self._active:
                raise RuntimeError("Cannot trigger reaction while idle")
            if self._reaction_policy is None:
                raise RuntimeError("No reaction policy configured")
            name, config = self._reaction_policy.select(category)
            # Definitions may have an artistic name (for example ``triple_tap``)
            # while their executable Stage 4 strategy is ``multi_tap``.
            return self._modulation.trigger(config.pop("type", name), **config)

    def step(self):
        """Advance both clocks' work without allowing logical pause to affect timeout."""
        with self._changed:
            if not self._active:
                return 0
            if self._clock.now() - self._started_at >= self._session_timeout:
                self._finish_session("timeout")
                self._changed.notify_all()
                return 0
            dispatched = self._engine.step()
            dispatched += self._modulation.step()
            backend_idle = getattr(self._dispatcher, "is_idle", lambda: True)
            if self._engine.is_complete and self._modulation.pending_count == 0 and backend_idle():
                self._finish_session("complete")
                self._changed.notify_all()
            return dispatched

    def wait_until_active(self):
        with self._changed:
            while not self._active:
                self._changed.wait()

    def wait_for_change(self, timeout):
        with self._changed:
            self._changed.wait(timeout)

    def _finish_session(self, reason):
        """Single teardown path: close admission, clear session work, quiesce, idle."""
        print(f"[Session] TEARDOWN: {reason}; closing session admission")
        self._active = False
        self._modulation.cancel()
        self._engine.stop()
        quiesce = getattr(self._dispatcher, "quiesce", None)
        if quiesce is not None:
            quiesce()
        print("[Session] IDLE: session state cleared; hardware quiescent")
