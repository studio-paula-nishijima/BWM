"""Transport-independent installation activation state."""

import threading


class ActivationController:
    """Own application activation and pause/resume an injected playback engine."""

    def __init__(self, playback_engine, initially_active=True):
        self._engine = playback_engine
        self._active = initially_active
        self._changed = threading.Condition()

    @property
    def is_active(self):
        with self._changed:
            return self._active

    def start(self):
        self._engine.start()
        if not self.is_active:
            self._engine.pause()

    def activate(self):
        with self._changed:
            if self._active:
                return False
            self._active = True
            self._engine.resume()
            self._changed.notify_all()
            return True

    def deactivate(self):
        with self._changed:
            if not self._active:
                return False
            self._active = False
            self._engine.pause()
            self._changed.notify_all()
            return True

    def toggle(self):
        return self.deactivate() if self.is_active else self.activate()

    def wait_until_active(self):
        """Block without polling until a local or future remote input activates."""
        with self._changed:
            while not self._active:
                self._changed.wait()

    def wait_for_change(self, timeout):
        """Sleep until activation changes or the active playback cadence expires."""
        with self._changed:
            self._changed.wait(timeout)
