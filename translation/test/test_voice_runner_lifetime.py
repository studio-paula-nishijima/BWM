import ast
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT / "translation" / "src"))

from live.voice_runtime import VoiceLifecycle, VoiceState
from live.voice_session import VoiceSessionController


class FakeTimer:
    def __init__(self, _seconds, callback):
        self.callback, self.cancelled, self.daemon = callback, False, False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


class FakeCapture:
    is_capturing = False


class FakeCoordinator:
    def __init__(self):
        self.lifecycle = VoiceLifecycle(emit=lambda _message: None)
        self.capture = FakeCapture()
        self.started = self.quiesced = self.reactivated = self.shutdowns = 0

    @property
    def interaction_admitted(self):
        return self.capture.is_capturing or self.lifecycle.state in (
            VoiceState.WHISPER_DETECTED, VoiceState.CAPTURE_PROCESSING, VoiceState.RESPONSE_DISPLAYED)

    def start(self):
        self.started += 1
        self.lifecycle.set(VoiceState.LISTENING)

    def quiesce(self):
        self.quiesced += 1

    def reactivate(self):
        self.reactivated += 1
        self.lifecycle.set(VoiceState.INITIALIZING)
        self.lifecycle.set(VoiceState.LISTENING)

    def shutdown(self):
        self.shutdowns += 1
        self.lifecycle.set(VoiceState.IDLE)


class VoiceRunnerLifetimeTests(unittest.TestCase):
    def _session(self):
        coordinator, timers = FakeCoordinator(), []
        session = VoiceSessionController(
            coordinator,
            active_period_seconds=1,
            timer_factory=lambda seconds, callback: timers.append(FakeTimer(seconds, callback)) or timers[-1],
        )
        return session, coordinator, timers

    def test_timeout_quiesces_without_process_cleanup_and_later_active_restarts(self):
        session, coordinator, timers = self._session()
        session.start()
        timers[-1].callback()

        self.assertTrue(session.quiescent)
        self.assertEqual(coordinator.quiesced, 1)
        self.assertEqual(coordinator.shutdowns, 0)
        self.assertEqual(coordinator.lifecycle.state, VoiceState.LISTENING)

        session.activation_received("active")
        self.assertFalse(session.quiescent)
        self.assertEqual(coordinator.reactivated, 1)
        self.assertEqual(coordinator.shutdowns, 0)
        self.assertEqual(len(timers), 2)

    def test_production_runner_has_no_legacy_duration_exit_condition(self):
        runtime_path = REPOSITORY_ROOT / "translation" / "whisper_runtime.py"
        tree = ast.parse(runtime_path.read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertNotIn("RUN_DURATION_SECONDS", names)

    def test_service_still_restarts_only_on_failure(self):
        unit = (REPOSITORY_ROOT / "services" / "voice_rack_services" / "whisper-runtime.service").read_text(encoding="utf-8")
        self.assertIn("Restart=on-failure", unit)


if __name__ == "__main__":
    unittest.main()
