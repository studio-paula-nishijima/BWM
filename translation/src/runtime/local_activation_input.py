"""GPIO adapter for the independent local installation activation fallback."""


class LocalActivationInput:
    """Translate a falling GPIO button edge into an activation toggle."""

    # Match the established physical-button debounce interval used by the
    # Voice backup control.  One mechanical press must produce one toggle.
    DEFAULT_BOUNCE_TIME_SECONDS = 0.4

    def __init__(self, pin, activation_controller, input_factory=None,
                 bounce_time=DEFAULT_BOUNCE_TIME_SECONDS):
        if input_factory is None:
            # Keep this hardware import out of test/import-only paths.
            from gpiozero import DigitalInputDevice
            input_factory = DigitalInputDevice
        self._device = input_factory(pin, pull_up=True, bounce_time=bounce_time)
        self._device.when_deactivated = activation_controller.toggle

    def close(self):
        self._device.close()
