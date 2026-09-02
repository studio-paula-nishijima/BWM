"""Asynchronous PCA9685 servo-rack controller with lazy hardware imports."""

import random
import threading
import time


def nominal_sequence_durations(min_pulse, max_pulse, *, frame_seconds=.02):
    """Return the current motion-program durations without changing the program.

    This is observability for the detector's seven-second start-to-start
    cooldown. Actual hardware execution remains protected by ``_busy``.
    """
    distance = max_pulse - min_pulse
    constant = lambda speed: int(abs(distance) / (speed * frame_seconds)) * frame_seconds
    return {
        1: .5 + 3.0 + 1.5,
        2: .3 + 1.5 + 1.5 + 2.0 + 1.5,
        3: .3 + constant(800) + 1.0 + constant(500),
        4: .3 + 1.5 + 1.8 + constant(1200) + .2 + constant(1000),
        5: .3 + constant(500) + 1.5,
    }


class ServoActuationController:
    def __init__(self, config, *, servo_factory=None, random_choice=None, clock=time.monotonic):
        self.config = dict(config)
        self._clock = clock
        self._random_choice = random_choice or random.choice
        self._lock = threading.Lock()
        self._worker = None
        self._closed = False
        self._last_started = float("-inf")
        self._busy = False
        if servo_factory is None:
            from servo.controller import ServoController
            servo_factory = ServoController
        self._servo = servo_factory(channel=self.config["channel"], frequency=self.config["frequency"], home_pulse=self.config["home_pulse"])
        self._servo.go_home()

    def actuate(self, sequence=None):
        with self._lock:
            if self._closed:
                return {"requested": True, "started": False, "suppression_reason": "shutdown"}
            if self._busy:
                return {"requested": True, "started": False, "suppression_reason": "busy"}
            if self._clock() - self._last_started < self.config["cooldown_seconds"]:
                return {"requested": True, "started": False, "suppression_reason": "cooldown"}
            self._busy = True
            self._last_started = self._clock()
            sequence = self._random_choice((1, 2, 3, 4, 5)) if sequence is None else int(sequence)
            if sequence not in (1, 2, 3, 4, 5):
                raise ValueError("servo sequence must be 1 through 5")
            self._worker = threading.Thread(target=self._run_sequence, args=(sequence,), daemon=True)
            self._worker.start()
            return {"requested": True, "started": True, "sequence": sequence, "suppression_reason": None}

    def _run_sequence(self, sequence):
        try:
            from servo.sweeps import simple_sweep, constant_speed
            set_pulse = self._servo.set_pulse
            low, high = self.config["min_pulse"], self.config["max_pulse"]
            print(f"SERVO: trigger sequence:{sequence}")
            if sequence == 1:
                simple_sweep(set_pulse, low, .5); simple_sweep(set_pulse, high, 3.0); simple_sweep(set_pulse, low, 1.5)
            elif sequence == 2:
                simple_sweep(set_pulse, low, .3); simple_sweep(set_pulse, high, 1.5); simple_sweep(set_pulse, low, 1.5); simple_sweep(set_pulse, low, 2.0); simple_sweep(set_pulse, low, 1.5)
            elif sequence == 3:
                simple_sweep(set_pulse, low, .3); constant_speed(set_pulse, low, high, 800); time.sleep(1); constant_speed(set_pulse, high, low, 500)
            elif sequence == 4:
                simple_sweep(set_pulse, low, .3); simple_sweep(set_pulse, high, 1.5); simple_sweep(set_pulse, low, 1.8); constant_speed(set_pulse, low, high, 1200); time.sleep(.2); constant_speed(set_pulse, high, low, 1000)
            else:
                simple_sweep(set_pulse, low, .3); constant_speed(set_pulse, low, high, 500); simple_sweep(set_pulse, low, 1.5)
        finally:
            with self._lock:
                self._busy = False

    def shutdown(self):
        with self._lock:
            self._closed = True
            worker = self._worker
        if worker and worker is not threading.current_thread():
            worker.join()
        self._servo.shutdown()
