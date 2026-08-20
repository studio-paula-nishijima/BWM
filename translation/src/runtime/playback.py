"""Stateful progression of an already-prepared base score.

The dispatch hook is deliberately the only boundary between a due base event
and hardware routing. A later runtime-modulation stage can refine that hook
without changing score preparation or the engine's timing responsibilities.
"""


class PlaybackEngine:
    """Dispatch prepared events as their ``playback_time`` becomes due."""

    READY = "ready"
    RUNNING = "running"
    COMPLETE = "complete"
    STOPPED = "stopped"

    def __init__(self, events, clock, dispatcher, event_logger=None):
        self._events = tuple(events)
        self._clock = clock
        self._dispatcher = dispatcher
        self._event_logger = event_logger
        self._event_index = 0
        self._started_at = None
        self._elapsed_time = 0.0
        self._state = self.READY

    @property
    def state(self):
        return self._state

    @property
    def event_index(self):
        return self._event_index

    @property
    def event_count(self):
        return len(self._events)

    @property
    def elapsed_time(self):
        return self._elapsed_time

    @property
    def is_running(self):
        return self._state == self.RUNNING

    @property
    def is_complete(self):
        return self._state == self.COMPLETE

    def start(self):
        """Begin progression from the clock's current reference point."""
        if self._state != self.READY:
            return

        self._started_at = self._clock.now()
        if not self._events:
            self._state = self.COMPLETE
            return
        self._state = self.RUNNING

    def stop(self):
        """Prevent further dispatch; hardware shutdown remains the caller's job."""
        if self._state == self.RUNNING:
            self._elapsed_time = self._clock.now() - self._started_at
            self._state = self.STOPPED

    def step(self):
        """Dispatch every pending event due at the current playback position."""
        if not self.is_running:
            return 0

        self._elapsed_time = self._clock.now() - self._started_at
        dispatched = 0
        while (
            self._event_index < self.event_count
            and self._events[self._event_index]["playback_time"] <= self._elapsed_time
        ):
            event = self._events[self._event_index]
            self._dispatch_due_event(event)
            self._event_index += 1
            dispatched += 1

        if self._event_index == self.event_count:
            self._state = self.COMPLETE
        return dispatched

    def _dispatch_due_event(self, event):
        """Single future insertion point between base timing and routing."""
        if self._event_logger is not None:
            self._event_logger(event)
        self._dispatcher.dispatch(event)
