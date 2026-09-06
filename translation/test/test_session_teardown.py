import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runtime.clock import SimulatedClock
from runtime.gpio_backend import GPIOBackend
from runtime.playback import PlaybackEngine
from runtime.router import EventRouter
from runtime.session import PlaybackSessionRuntime


def event(at=0, target="a", duration=.15):
    return {"type": "solenoid", "playback_time": at, "target": target, "duration": duration}


class FakeDevice:
    def __init__(self, pin):
        self.pin, self.is_active, self.closed, self.on_count, self.off_count = pin, False, False, 0, 0
    def on(self):
        self.is_active, self.on_count = True, self.on_count + 1
        if hasattr(self, "on_signal"):
            self.on_signal.set()
    def off(self): self.is_active, self.off_count = False, self.off_count + 1
    def close(self): self.closed = True


class SessionDispatcher:
    def __init__(self): self.events, self.quiesce_count, self.begin_count = [], 0, 0
    def dispatch(self, item): self.events.append(item)
    def quiesce(self): self.quiesce_count += 1
    def begin_session(self): self.begin_count += 1


class ActivationFadeLighting:
    def __init__(self, delay):
        self.activation_delay_seconds, self.activate_count, self.step_count = delay, 0, 0
    def activate(self): self.activate_count += 1
    def step(self): self.step_count += 1
    def deactivate_async(self): pass


class SessionTeardownTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.dispatcher = SimulatedClock(), SessionDispatcher()

    def test_timeout_and_cancel_share_quiesce_path_and_preserve_safety(self):
        runtime = PlaybackSessionRuntime(lambda: [event(10)], self.clock, self.dispatcher, 2,
                                         safety_config={"thermal": {"enabled": True}})
        runtime.activate(); self.assertEqual(self.dispatcher.begin_count, 1)
        runtime.safety.dispatch(event())
        history = runtime.safety.observations("a")["accepted_count"]
        runtime.trigger("multi_tap", repeat_count=3, inter_tap_delay=10)
        self.clock.advance(2); runtime.step()
        self.assertFalse(runtime.is_active)
        self.assertEqual(runtime.modulation.pending_count, 0)
        self.assertEqual(self.dispatcher.quiesce_count, 1)
        runtime.activate(); runtime.deactivate()
        self.assertEqual(self.dispatcher.quiesce_count, 2)
        self.assertEqual(runtime.safety.observations("a")["accepted_count"], history)

    def test_no_delayed_modulation_leaks_to_next_session(self):
        sessions = [[event()], [event(target="fresh")]]
        runtime = PlaybackSessionRuntime(lambda: sessions.pop(0), self.clock, self.dispatcher, 30)
        runtime.activate(); runtime.trigger("multi_tap", repeat_count=2, inter_tap_delay=5,
                                           base_treatment="suppress")
        runtime.step(); runtime.deactivate()
        self.clock.advance(10); runtime.activate(); runtime.step()
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["a", "fresh"])

    def test_halo_activation_fade_opens_solenoid_admission_only_after_normal_brightness(self):
        lighting = ActivationFadeLighting(delay=4)
        runtime = PlaybackSessionRuntime(lambda: [event(0)], self.clock, self.dispatcher, 30,
                                         lighting_controller=lighting)
        runtime.activate()
        self.assertEqual(runtime.engine.state, PlaybackEngine.READY)
        self.assertEqual(lighting.activate_count, 1)
        runtime.step()
        self.assertEqual(self.dispatcher.events, [])
        self.clock.advance(3.999); runtime.step()
        self.assertEqual(self.dispatcher.events, [])
        self.clock.advance(.001); runtime.step()
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["a"])


class GPIOBackendTeardownTests(unittest.TestCase):
    def setUp(self):
        self.started, self.release = threading.Event(), threading.Event()
        self.device_signals = {}
        def device_factory(pin):
            device = FakeDevice(pin)
            device.on_signal = self.device_signals.setdefault(pin, threading.Event())
            return device
        def blocking_sleep(duration):
            self.started.set()
            self.release.wait(1)
        self.backend = GPIOBackend({"north": 5, "south": 6}, device_factory=device_factory,
                                   sleep_fn=blocking_sleep)

    def tearDown(self):
        self.release.set()
        self.backend.shutdown()

    def test_quiesce_clears_queued_work_waits_for_active_pulse_and_reuses_backend(self):
        self.backend.pulse("north", .15)
        self.backend.pulse("north", .15)
        self.assertTrue(self.started.wait(1))
        quiesce = threading.Thread(target=self.backend.quiesce)
        quiesce.start()
        self.assertTrue(quiesce.is_alive())  # active normal pulse is allowed to finish.
        self.release.set(); quiesce.join(1)
        device = self.backend.devices["north"]
        self.assertFalse(device.is_active)
        self.assertEqual(device.on_count, 1)  # queued second pulse was never started.
        self.assertFalse(self.backend.pulse("north", .15))
        self.backend.begin_session()
        self.assertTrue(self.backend.pulse("south", .15))
        self.assertTrue(self.device_signals[6].wait(1))
        self.backend.queues["south"].join()
        self.assertGreater(self.backend.devices["south"].on_count, 0)
        self.assertFalse(self.backend.devices["south"].is_active)

    def test_shutdown_releases_devices_unlike_quiesce(self):
        self.backend.quiesce()
        self.assertFalse(any(device.closed for device in self.backend.devices.values()))
        self.backend.shutdown()
        self.assertTrue(all(device.closed for device in self.backend.devices.values()))

    def test_completed_score_allows_its_admitted_pulse_before_teardown(self):
        runtime = PlaybackSessionRuntime(lambda: [event(target="north")], SimulatedClock(),
                                         EventRouter({"solenoid": self.backend}), 30)
        runtime.activate(); runtime.step()
        self.assertTrue(runtime.is_active)
        self.backend.queues["north"].join()
        runtime.step()
        self.assertFalse(runtime.is_active)
        self.assertEqual(self.backend.devices["north"].on_count, 1)
        self.assertFalse(self.backend.devices["north"].is_active)


if __name__ == "__main__":
    unittest.main()
