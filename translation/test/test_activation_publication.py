import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "translation" / "src"))

from runtime.activation_publication import TranslationActivationPublisher
from runtime.clock import SimulatedClock
from runtime.local_activation_input import LocalActivationInput
from runtime.mqtt_adapter import TranslationSemanticIngress
from runtime.session import PlaybackSessionRuntime
from shared.messaging.events import installation_activation
from shared.messaging.topics import TopicNamespace


class Dispatcher:
    def begin_session(self):
        pass

    def dispatch(self, _event):
        pass

    def quiesce(self):
        pass


class UART:
    def __init__(self, succeeds=True):
        self.succeeds, self.events = succeeds, []

    def send(self, event):
        self.events.append(event)
        return self.succeeds


class GPIOInput:
    def __init__(self, _pin, *, pull_up, bounce_time):
        self.pull_up, self.bounce_time = pull_up, bounce_time
        self.when_activated, self.when_deactivated = None, None
    def close(self):
        pass


class MonotonicClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def runtime(*, initially_active=True, publisher=None):
    sessions = [[{"playback_time": 0, "target": "one"}], [{"playback_time": 0, "target": "two"}]]
    return PlaybackSessionRuntime(lambda: sessions.pop(0), SimulatedClock(), Dispatcher(), 600,
                                  initially_active=initially_active,
                                  activation_publisher=publisher)


class AuthoritativeActivationPublicationTests(unittest.TestCase):
    def test_initially_active_boot_needs_no_uart_then_can_publish_startup_state(self):
        app = runtime(initially_active=True)
        self.assertTrue(app.is_active)
        uart = UART()
        app.set_activation_publisher(TranslationActivationPublisher(uart, emit=lambda _: None))
        app.publish_current_activation()
        self.assertTrue(app.is_active)
        self.assertEqual([event.payload["state"] for event in uart.events], ["active"])

    def test_failed_startup_publication_does_not_stop_initial_session(self):
        uart = UART(succeeds=False)
        app = runtime(initially_active=True,
                      publisher=TranslationActivationPublisher(uart, emit=lambda _: None))
        app.publish_current_activation()
        self.assertTrue(app.is_active)
        self.assertEqual([event.payload["state"] for event in uart.events], ["active"])

    def test_transition_publication_is_new_translation_event_and_deduplicated_by_state(self):
        uart = UART()
        app = runtime(initially_active=True,
                      publisher=TranslationActivationPublisher(uart, emit=lambda _: None))
        incoming = installation_activation("person_detector", "inactive", id="incoming")
        ingress = TranslationSemanticIngress(app, TopicNamespace().installation_activation)
        self.assertTrue(ingress.handle(TopicNamespace().installation_activation, incoming))
        self.assertFalse(ingress.handle(TopicNamespace().installation_activation,
                                        installation_activation("person_detector", "inactive", id="again")))
        self.assertTrue(ingress.handle(TopicNamespace().installation_activation,
                                       installation_activation("person_detector", "active", id="resume")))
        self.assertEqual([event.payload["state"] for event in uart.events], ["inactive", "active"])
        self.assertTrue(all(event.origin == "translation_pi" for event in uart.events))
        self.assertNotEqual(uart.events[0].id, incoming.id)

    def test_ble_style_transport_transition_publishes_and_uart_input_does_not_echo(self):
        uart = UART()
        app = runtime(initially_active=False,
                      publisher=TranslationActivationPublisher(uart, emit=lambda _: None))
        ingress = TranslationSemanticIngress(app, TopicNamespace().installation_activation)
        self.assertTrue(ingress.handle_event(installation_activation("person_detector", "active", id="ble")))
        self.assertEqual([event.payload["state"] for event in uart.events], ["active"])
        self.assertTrue(ingress.handle_event(installation_activation("whisper_pi", "inactive", id="uart"),
                                             publish_authoritative=False))
        self.assertFalse(app.is_active)
        self.assertEqual([event.payload["state"] for event in uart.events], ["active"])

    def test_uart_send_failure_never_rolls_back_authoritative_state(self):
        uart = UART(succeeds=False)
        app = runtime(initially_active=False,
                      publisher=TranslationActivationPublisher(uart, emit=lambda _: None))
        self.assertTrue(app.activate())
        self.assertTrue(app.is_active)
        self.assertEqual(len(uart.events), 1)

    def test_gpio17_press_debounce_preserves_publication_path(self):
        uart = UART()
        app = runtime(initially_active=True,
                      publisher=TranslationActivationPublisher(uart, emit=lambda _: None))
        clock = MonotonicClock()
        gpio = LocalActivationInput(17, app, input_factory=GPIOInput, monotonic_clock=clock)
        self.assertIsNone(gpio._device.bounce_time)
        gpio._device.when_activated()
        clock.advance(0.4)
        gpio._device.when_activated()
        self.assertEqual([event.payload["state"] for event in uart.events], ["inactive", "active"])


if __name__ == "__main__":
    unittest.main()
