"""GPIO adapter for the independent local installation activation fallback."""

import time


class LocalActivationInput:
    """Translate accepted active-low GPIO17 press edges into activation toggles."""

    # Match the established physical-button debounce interval used by the
    # Voice backup control.  One mechanical press must produce one toggle.
    DEFAULT_BOUNCE_TIME_SECONDS = 0.4

    def __init__(self, pin, activation_controller, input_factory=None,
                 bounce_time=DEFAULT_BOUNCE_TIME_SECONDS, monotonic_clock=None):
        if input_factory is None:
            # Keep this hardware import out of test/import-only paths.
            from gpiozero import DigitalInputDevice
            input_factory = DigitalInputDevice
        self._activation_controller = activation_controller
        self._bounce_time = bounce_time
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._last_accepted_press = None

        # GPIOZero's backend debounce suppresses the release edge after a
        # short press.  Keep the hardware input un-debounced and apply the
        # established 0.4 s dead-time after accepting a press instead.
        self._device = input_factory(pin, pull_up=True, bounce_time=None)
        self._device.when_activated = self._handle_press

    def _handle_press(self):
        """Toggle once for an accepted falling (active-low) button edge."""
        now = self._monotonic_clock()
        if (self._last_accepted_press is not None
                and now - self._last_accepted_press < self._bounce_time):
            return
        self._last_accepted_press = now
        self._activation_controller.toggle()

    def close(self):
        self._device.close()
