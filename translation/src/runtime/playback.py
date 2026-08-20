"""Stateful progression of an already-prepared base score.

The dispatch hook is deliberately the only boundary between a due base event
and hardware routing. A later runtime-modulation stage can refine that hook
without changing score preparation or the engine's timing responsibilities.
"""


class PlaybackEngine:
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETE = "complete"
    STOPPED = "stopped"

    def __init__(self, events, clock, dispatcher, event_logger=None):
        self._events, self._clock, self._dispatcher = tuple(events), clock, dispatcher
        self._event_logger = event_logger
        self._event_index, self._started_at, self._elapsed_time = 0, None, 0.0
        self._state = self.READY

    @property
    def state(self): return self._state

    @property
    def event_index(self): return self._event_index

    @property
    def event_count(self): return len(self._events)

    @property
    def elapsed_time(self): return self._elapsed_time

    @property
    def is_running(self): return self._state == self.RUNNING

    @property
    def is_paused(self): return self._state == self.PAUSED

    @property
    def is_complete(self): return self._state == self.COMPLETE

    @property
    def is_terminal(self): return self._state in (self.COMPLETE, self.STOPPED)

    def start(self):
        if self._state != self.READY:
            return
        self._started_at = self._clock.now()
        self._state = self.COMPLETE if not self._events else self.RUNNING

    def pause(self):
        if self.is_running:
            self._elapsed_time = self._clock.now() - self._started_at
            self._state = self.PAUSED

    def resume(self):
        if self.is_paused:
            self._started_at = self._clock.now() - self._elapsed_time
            self._state = self.RUNNING

    def stop(self):
        if self.is_running:
            self._elapsed_time = self._clock.now() - self._started_at
        if self._state in (self.RUNNING, self.PAUSED):
            self._state = self.STOPPED

    def step(self):
        if not self.is_running:
            return 0
        self._elapsed_time = self._clock.now() - self._started_at
        dispatched = 0
        while (self._event_index < self.event_count
               and self._events[self._event_index]["playback_time"] <= self._elapsed_time):
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
