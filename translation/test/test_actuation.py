import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from actuation.runtime import DelayedInteractionServo, resolve_actuation_enabled, request_for_emitted_trigger
from actuation.servo_controller import ServoActuationController, nominal_sequence_durations


class ActuationTests(unittest.TestCase):
    def test_source_defaults_and_explicit_overrides(self):
        self.assertTrue(resolve_actuation_enabled(wav_path=None))
        self.assertFalse(resolve_actuation_enabled(wav_path="example.wav"))
        self.assertFalse(resolve_actuation_enabled(wav_path=None, no_actuation=True))
        self.assertTrue(resolve_actuation_enabled(wav_path="example.wav", enable_actuation=True))
        with self.assertRaises(ValueError):
            resolve_actuation_enabled(wav_path=None, enable_actuation=True, no_actuation=True)

    def test_only_real_emitted_trigger_requests_hardware(self):
        class Recorder:
            def __init__(self): self.requests = 0
            def actuate(self):
                self.requests += 1
                return {"requested": True, "started": True}

        recorder = Recorder()
        self.assertIsNone(request_for_emitted_trigger(emitted_trigger=False, controller=recorder))
        self.assertEqual(recorder.requests, 0)
        self.assertTrue(request_for_emitted_trigger(emitted_trigger=True, controller=recorder)["started"])
        self.assertEqual(recorder.requests, 1)

    def test_each_emitted_trigger_gets_its_own_delayed_schedule_and_shutdown_cancels(self):
        class Timer:
            created = []
            def __init__(self, delay, callback):
                self.delay, self.callback, self.daemon, self.started, self.cancelled = delay, callback, False, False, False
                self.__class__.created.append(self)
            def start(self): self.started = True
            def cancel(self): self.cancelled = True
        class Controller:
            def __init__(self): self.requests = 0
            def actuate(self): self.requests += 1; return {"started": True}

        emitted, controller = [], Controller()
        servo = DelayedInteractionServo(controller, 3.0, emit=emitted.append, timer_factory=Timer)
        # Only calls made from the emitted-trigger seam schedule work; the
        # scheduler deliberately keeps both valid occurrences independent.
        servo.schedule(); servo.schedule()
        self.assertEqual([timer.delay for timer in Timer.created], [3.0, 3.0])
        self.assertTrue(all(timer.started for timer in Timer.created))
        Timer.created[0].callback()
        self.assertEqual(controller.requests, 1)
        self.assertIn("[Servo] actuated", emitted)
        servo.cancel()
        self.assertTrue(all(timer.cancelled for timer in Timer.created))

    def test_delayed_servo_reports_controller_busy_or_cooldown(self):
        class Timer:
            def __init__(self, _delay, callback): self.callback, self.daemon = callback, False
            def start(self): pass
            def cancel(self): pass
        emitted = []
        servo = DelayedInteractionServo(type("Controller", (), {"actuate": lambda self: {"started": False, "suppression_reason": "busy"}})(),
                                        3, emit=emitted.append, timer_factory=Timer)
        servo.schedule()
        next(iter(servo._timers)).callback()
        self.assertIn("[Servo] suppressed: busy", emitted)

    def test_existing_motion_program_fits_detector_cooldown_and_busy_prevents_overlap(self):
        durations = nominal_sequence_durations(800, 2200)
        self.assertEqual(durations[2], 6.8)  # longest unchanged program
        self.assertLess(max(durations.values()), 7.0)

        class Servo:
            def go_home(self): pass
            def shutdown(self): pass
        class Thread:
            def __init__(self, *args, **kwargs): pass
            def start(self): pass
        import actuation.servo_controller as module
        original_thread = module.threading.Thread
        module.threading.Thread = Thread
        try:
            controller = ServoActuationController({"channel": 0, "frequency": 50, "min_pulse": 800,
                                                    "max_pulse": 2200, "home_pulse": 800,
                                                    "cooldown_seconds": 0}, servo_factory=lambda **_: Servo())
            self.assertTrue(controller.actuate()["started"])
            self.assertEqual(controller.actuate()["suppression_reason"], "busy")
        finally:
            module.threading.Thread = original_thread


if __name__ == "__main__":
    unittest.main()
