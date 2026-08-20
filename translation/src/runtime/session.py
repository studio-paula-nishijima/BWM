"""Persistent activation runtime with wall-clock bounded playback sessions."""

import threading

from runtime.modulation import RuntimeModulationEngine
from runtime.playback import PlaybackEngine


class PlaybackSessionRuntime:
    """Keep an installation runtime alive while creating clean sessions on activation."""

    def __init__(self, events_factory, clock, dispatcher, session_timeout, initially_active=False,
                 event_logger=None):
        self._events_factory, self._clock, self._dispatcher = events_factory, clock, dispatcher
        self._session_timeout, self._event_logger = float(session_timeout), event_logger
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

    def activate(self):
        with self._changed:
            if self._active:
                return False
            modulation = RuntimeModulationEngine(self._clock, self._dispatcher)
            engine = PlaybackEngine(self._events_factory(), self._clock,
                                    due_event_handler=modulation.process,
                                    event_logger=self._event_logger)
            modulation.bind_playback_control(engine)
            engine.start()
            self._engine, self._modulation = engine, modulation
            self._started_at, self._active = self._clock.now(), True
            self._changed.notify_all()
            return True

    def deactivate(self):
        """Explicit cancellation, not a logical-score pause."""
        with self._changed:
            if not self._active:
                return False
            self._finish_session()
            self._changed.notify_all()
            return True

    cancel = deactivate

    def toggle(self):
        return self.deactivate() if self.is_active else self.activate()

    def trigger(self, name, **config):
        if not self._active:
            raise RuntimeError("Cannot trigger modulation while idle")
        return self._modulation.trigger(name, **config)

    def step(self):
        """Advance both clocks' work without allowing logical pause to affect timeout."""
        if not self._active:
            return 0
        if self._clock.now() - self._started_at >= self._session_timeout:
            self.deactivate()
            return 0
        dispatched = self._engine.step()
        dispatched += self._modulation.step()
        if self._engine.is_complete and self._modulation.pending_count == 0:
            self.deactivate()
        return dispatched

    def wait_until_active(self):
        with self._changed:
            while not self._active:
                self._changed.wait()

    def wait_for_change(self, timeout):
        with self._changed:
            self._changed.wait(timeout)

    def _finish_session(self):
        # cancel resumes a reaction pause before stopping so it cannot leak.
        self._modulation.cancel()
        self._engine.stop()
        self._active = False
