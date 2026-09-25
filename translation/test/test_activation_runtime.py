import sys
import threading
import unittest
from pathlib import Path

TRANSLATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRANSLATION_ROOT / "src"))

from runtime.activation import ActivationController
from runtime.clock import SimulatedClock
from runtime.local_activation_input import LocalActivationInput
from runtime.playback import PlaybackEngine
from play_events import run_engine


def event(at, target):
    return {"playback_time": at, "target": target}


class FakeDispatcher:
    def __init__(self):
        self.events = []

    def dispatch(self, due_event):
        self.events.append(due_event)


class FakeInput:
    instances = []

    def __init__(self, pin, pull_up, bounce_time):
        self.pin, self.pull_up, self.bounce_time = pin, pull_up, bounce_time
        self.when_activated, self.when_deactivated, self.closed = None, None, False
        self.instances.append(self)

    def close(self):
        self.closed = True

    def emit_press(self):
        if self.when_activated is not None:
            self.when_activated()

    def emit_release(self):
        if self.when_deactivated is not None:
            self.when_deactivated()


class FakeMonotonicClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ActivationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.clock = SimulatedClock()
        self.dispatcher = FakeDispatcher()
        self.engine = PlaybackEngine(
            [event(0, "first"), event(1, "second"), event(2, "third")],
            self.clock, self.dispatcher,
        )
        self.controller = ActivationController(self.engine)
        self.controller.start()

    def test_active_regression_and_completion_are_exactly_once(self):
        self.engine.step()
        self.clock.advance(2)
        self.engine.step()
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["first", "second", "third"])
        self.assertTrue(self.engine.is_complete)
        self.controller.deactivate()
        self.controller.activate()
        self.assertEqual(self.engine.step(), 0)
        self.assertEqual(len(self.dispatcher.events), 3)

    def test_deactivation_freezes_logical_score_and_reactivation_excludes_wall_time(self):
        self.engine.step()
        self.clock.advance(0.5)
        self.controller.deactivate()
        self.clock.advance(100)
        self.assertEqual(self.engine.step(), 0)
        self.assertEqual(self.engine.elapsed_time, 0.5)
        self.controller.activate()
        self.clock.advance(0.5)
        self.engine.step()
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["first", "second"])

    def test_repeated_cycles_do_not_skip_or_duplicate_events(self):
        self.engine.step()
        for _ in range(2):
            self.clock.advance(0.4)
            self.controller.deactivate()
            self.clock.advance(10)
            self.controller.activate()
        self.clock.advance(0.2)
        self.engine.step()
        self.clock.advance(1)
        self.engine.step()
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["first", "second", "third"])

    def test_stop_is_terminal_and_deactivate_is_not(self):
        self.controller.deactivate()
        self.assertTrue(self.engine.is_paused)
        self.engine.stop()
        self.controller.activate()
        self.clock.advance(10)
        self.assertEqual(self.engine.state, PlaybackEngine.STOPPED)
        self.assertEqual(self.engine.step(), 0)

    def test_gpio_adapter_short_press_toggles_on_press_not_release(self):
        clock = FakeMonotonicClock()
        local_input = LocalActivationInput(
            17, self.controller, FakeInput, monotonic_clock=clock,
        )
        device = FakeInput.instances[-1]
        self.assertEqual(device.pin, 17)
        self.assertTrue(device.pull_up)
        self.assertIsNone(device.bounce_time)
        self.assertIsNotNone(device.when_activated)
        self.assertIsNone(device.when_deactivated)

        # Initial released/high state invokes no callback.
        self.assertTrue(self.controller.is_active)

        # A short active-low press toggles immediately; its release does not.
        device.emit_press()
        self.assertFalse(self.controller.is_active)
        clock.advance(0.1)
        device.emit_release()
        self.assertFalse(self.controller.is_active)
        local_input.close()
        self.assertTrue(device.closed)

    def test_gpio_adapter_long_press_toggles_once(self):
        clock = FakeMonotonicClock()
        local_input = LocalActivationInput(
            17, self.controller, FakeInput, monotonic_clock=clock,
        )
        device = FakeInput.instances[-1]
        device.emit_press()
        self.assertFalse(self.controller.is_active)
        clock.advance(1.0)
        device.emit_release()
        self.assertFalse(self.controller.is_active)
        local_input.close()

    def test_gpio_adapter_uses_point_four_second_post_acceptance_dead_time(self):
        clock = FakeMonotonicClock()
        local_input = LocalActivationInput(
            17, self.controller, FakeInput, monotonic_clock=clock,
        )
        device = FakeInput.instances[-1]
        device.emit_press()
        self.assertFalse(self.controller.is_active)

        clock.advance(0.2)
        device.emit_release()
        device.emit_press()
        self.assertFalse(self.controller.is_active)

        clock.advance(0.2)
        device.emit_release()
        device.emit_press()
        self.assertTrue(self.controller.is_active)
        local_input.close()

    def test_initially_inactive_engine_does_not_step(self):
        engine = PlaybackEngine([event(0, "first")], self.clock, self.dispatcher)
        controller = ActivationController(engine, initially_active=False)
        controller.start()
        self.assertTrue(engine.is_paused)
        self.assertEqual(engine.step(), 0)
        controller.activate()
        engine.step()
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["first"])

    def test_inactive_runtime_waits_for_activation_without_stepping(self):
        engine = PlaybackEngine([event(0, "first")], self.clock, self.dispatcher)
        controller = ActivationController(engine, initially_active=False)
        runner = threading.Thread(target=run_engine, args=(controller, engine, 0.001))
        runner.start()
        threading.Event().wait(0.02)
        self.assertEqual(self.dispatcher.events, [])
        self.assertTrue(runner.is_alive())
        controller.activate()
        runner.join(1)
        self.assertFalse(runner.is_alive())
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["first"])


if __name__ == "__main__":
    unittest.main()
