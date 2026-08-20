"""GPIO adapter for the independent local installation activation fallback."""


class LocalActivationInput:
    """Translate a falling GPIO button edge into an activation toggle."""

    def __init__(self, pin, activation_controller, input_factory=None):
        if input_factory is None:
            # Keep this hardware import out of test/import-only paths.
            from gpiozero import DigitalInputDevice
            input_factory = DigitalInputDevice
        self._device = input_factory(pin, pull_up=True)
        self._device.when_deactivated = activation_controller.toggle

    def close(self):
        self._device.close()
