import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audio.capture_health import (
    CaptureHealthConfig,
    CaptureHealthMonitor,
    CaptureHealthState,
    CaptureHealthSupervisor,
    RebootGuard,
    frame_signature,
)


class FakeSource:
    def __init__(self, opened, fail_open=False):
        self.opened, self.fail_open, self.closed = opened, fail_open, 0

    def open(self):
        self.opened.append(self)
        if self.fail_open:
            raise RuntimeError("open failed")

    def close(self):
        self.closed += 1


class MemoryGuard:
    def __init__(self, allowed=True):
        self.permitted, self.records = allowed, 0

    def allowed(self):
        return self.permitted

    def record(self):
        self.records += 1
        self.permitted = False


class CaptureHealthTests(unittest.TestCase):
    config = CaptureHealthConfig(unhealthy_window_seconds=2, recovery_verify_seconds=1,
                                 reboot_cooldown_seconds=3600)
    pathological = np.resize(np.array([0, -1], dtype=np.float32) / 32768, 480)
    quiet_noise = np.linspace(-0.00003, 0.00003, 480, dtype=np.float32)
    varying = np.sin(np.linspace(0, 1, 480, dtype=np.float32)) * .0001

    def test_signature_is_narrow_and_ordinary_silence_is_not_failure(self):
        self.assertTrue(frame_signature(self.pathological).pathological)
        self.assertFalse(frame_signature(np.zeros(480, dtype=np.float32)).pathological)
        self.assertFalse(frame_signature(self.quiet_noise).pathological)
        self.assertFalse(frame_signature(self.varying).pathological)

    def test_low_rms_variation_and_short_pathological_burst_do_not_fault(self):
        monitor = CaptureHealthMonitor(self.config)
        for now in (0, .5, 1, 1.5):
            self.assertIsNone(monitor.observe(self.quiet_noise, now))
        self.assertEqual(monitor.state, CaptureHealthState.HEALTHY)
        self.assertIsNone(monitor.observe(self.pathological, 2))
        self.assertIsNone(monitor.observe(self.pathological, 3.9))
        self.assertEqual(monitor.state, CaptureHealthState.SUSPECT)

    def test_sustained_pathology_declares_unhealthy_without_detector_input(self):
        monitor = CaptureHealthMonitor(self.config)
        self.assertIsNone(monitor.observe(self.pathological, 0))
        self.assertEqual(monitor.observe(self.pathological, 2), "unhealthy")
        self.assertEqual(monitor.state, CaptureHealthState.UNHEALTHY)

    def make_supervisor(self, sources, guard=None):
        opened, events, reboots, boundaries = [], [], [], []
        queue = list(sources)
        supervisor = CaptureHealthSupervisor(
            lambda: FakeSource(opened, fail_open=queue.pop(0)), self.config,
            emit=events.append, reboot_guard=guard or MemoryGuard(), reboot=lambda: reboots.append("reboot"),
            on_source_reopened=lambda: boundaries.append("reset"),
        )
        supervisor.open()
        return supervisor, opened, events, reboots, boundaries

    def test_first_fault_restarts_once_and_open_is_not_assumed_recovered(self):
        supervisor, opened, events, reboots, boundaries = self.make_supervisor([False, False])
        supervisor.observe(self.pathological, 0)
        supervisor.observe(self.pathological, 2)
        self.assertEqual(len(opened), 2)
        self.assertEqual(opened[0].closed, 1)
        self.assertEqual(supervisor.monitor.state, CaptureHealthState.VERIFYING)
        self.assertIn("[AudioHealth] verifying recovery", events)
        self.assertFalse(reboots)
        self.assertEqual(boundaries, ["reset"])

    def test_meaningful_variation_for_full_verify_window_recovers(self):
        supervisor, _, events, reboots, _ = self.make_supervisor([False, False])
        supervisor.observe(self.pathological, 0); supervisor.observe(self.pathological, 2)
        supervisor.observe(self.varying, 2.1)
        self.assertIsNone(supervisor.observe(self.varying, 2.9))
        self.assertEqual(supervisor.observe(self.varying, 3.1), "recovered")
        self.assertEqual(supervisor.monitor.state, CaptureHealthState.HEALTHY)
        self.assertIn("[AudioHealth] capture recovered", events)
        self.assertFalse(reboots)

    def test_failed_verification_escalates_once_and_cooldown_blocks_loop(self):
        guard = MemoryGuard()
        supervisor, opened, events, reboots, _ = self.make_supervisor([False, False], guard)
        supervisor.observe(self.pathological, 0); supervisor.observe(self.pathological, 2)
        supervisor.observe(self.pathological, 3)
        self.assertEqual(reboots, ["reboot"])
        supervisor.observe(self.pathological, 4)
        self.assertEqual(reboots, ["reboot"])
        self.assertEqual(len(opened), 2)
        self.assertEqual(events.count("[AudioHealth] escalating to controlled reboot"), 1)

    def test_existing_cooldown_suppresses_a_new_fault_episode_once(self):
        guard = MemoryGuard(allowed=False)
        supervisor, _, events, reboots, _ = self.make_supervisor([False, False], guard)
        supervisor.observe(self.pathological, 0); supervisor.observe(self.pathological, 2)
        supervisor.observe(self.pathological, 3); supervisor.observe(self.pathological, 4)
        self.assertFalse(reboots)
        self.assertEqual(events.count("[AudioHealth] reboot escalation suppressed by cooldown"), 1)

    def test_quiescence_resets_observation_and_reactivation_starts_fresh(self):
        supervisor, opened, _, _, _ = self.make_supervisor([False, False])
        supervisor.observe(self.pathological, 0)
        supervisor.set_active(False)
        supervisor.observe(self.pathological, 20)
        self.assertEqual(len(opened), 1)
        supervisor.set_active(True)
        supervisor.observe(self.pathological, 21)
        supervisor.observe(self.pathological, 22.9)
        self.assertEqual(len(opened), 1)
        supervisor.observe(self.pathological, 23)
        self.assertEqual(len(opened), 2)

    def test_persistent_guard_uses_cooldown(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            now = [1000]
            guard = RebootGuard(Path(directory) / "state.json", 60, wall_clock=lambda: now[0])
            self.assertTrue(guard.allowed())
            guard.record(); self.assertFalse(guard.allowed())
            now[0] += 60
            self.assertTrue(guard.allowed())


if __name__ == "__main__":
    unittest.main()
