"""GPIO interaction backup input for the Voice Pi (rpi02)."""
from __future__ import annotations

import time


class InteractionButton:
    """One pull-up, falling-edge button; callback only queues a logical press."""
    def __init__(self, pin, on_press, *, debounce_seconds=.4, pull_up=True,
                 emit=print, input_factory=None, monotonic=time.monotonic):
        self.pin, self.on_press = pin, on_press
        self.debounce_seconds, self.pull_up, self.emit, self._clock = debounce_seconds, pull_up, emit, monotonic
        self._last_press = float("-inf")
        if input_factory is None:
            from gpiozero import DigitalInputDevice
            input_factory = DigitalInputDevice
        self._device = input_factory(pin, pull_up=pull_up)
        self._device.when_pressed = self.handle_press

    def handle_press(self):
        now = self._clock()
        if now - self._last_press < self.debounce_seconds:
            return False
        self._last_press = now
        self.emit("[InteractionButton] pressed")
        self.on_press()
        return True

    def close(self):
        self._device.close()
