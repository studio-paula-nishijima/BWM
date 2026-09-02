import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live.interaction_button import InteractionButton
from live.semantic_ingress import VoiceSemanticIngress
from live.voice_runtime import VoiceLifecycle, VoiceState
from live.voice_session import VoiceSessionController
from shared.messaging.events import installation_activation


class FakeTimer:
    def __init__(self, _seconds, callback): self.callback, self.cancelled, self.daemon = callback, False, False
    def start(self): pass
    def cancel(self): self.cancelled = True


class FakeCapture:
    is_capturing = False


class FakeCoordinator:
    def __init__(self):
        self.lifecycle, self.capture = VoiceLifecycle(emit=lambda _: None), FakeCapture()
        self.started = self.quiesced = self.reactivated = 0
    @property
    def interaction_admitted(self):
        return self.capture.is_capturing or self.lifecycle.state in (VoiceState.WHISPER_DETECTED, VoiceState.CAPTURE_PROCESSING, VoiceState.RESPONSE_DISPLAYED)
    def start(self): self.started += 1; self.lifecycle.set(VoiceState.LISTENING)
    def quiesce(self): self.quiesced += 1
    def reactivate(self): self.reactivated += 1; self.lifecycle.set(VoiceState.INITIALIZING); self.lifecycle.set(VoiceState.LISTENING)


class FakeInput:
    def __init__(self, *_args, **_kwargs): self.when_pressed = None; self.closed = False
    def close(self): self.closed = True


class VoiceSessionTests(unittest.TestCase):
    def make(self):
        timers, events, coordinator = [], [], FakeCoordinator()
        session = VoiceSessionController(coordinator, active_period_seconds=600, emit=events.append,
            timer_factory=lambda seconds, callback: timers.append(FakeTimer(seconds, callback)) or timers[-1])
        return session, coordinator, timers, events

    def test_boots_active_and_arms_own_timer(self):
        session, coordinator, timers, events = self.make()
        session.start()
        self.assertEqual(coordinator.started, 1)
        self.assertTrue(session.admitting_interactions)
        self.assertEqual(len(timers), 1)
        self.assertIn("[VoiceSession] active; timer 600 s", events)

    def test_timeout_blocks_new_admission_and_quiesces(self):
        session, coordinator, timers, _ = self.make(); session.start()
        timers[-1].callback()
        self.assertFalse(session.admitting_interactions)
        self.assertTrue(session.quiescent)
        self.assertEqual(coordinator.quiesced, 1)

    def test_active_resets_timer_without_restarting_interaction(self):
        session, coordinator, timers, _ = self.make(); session.start()
        coordinator.lifecycle.set(VoiceState.CAPTURE_PROCESSING)
        session.activation_received("active")
        self.assertEqual(coordinator.reactivated, 0)
        self.assertFalse(timers[-1].cancelled)
        self.assertTrue(timers[-2].cancelled)
        self.assertEqual(coordinator.lifecycle.state, VoiceState.CAPTURE_PROCESSING)

    def test_inactive_waits_for_admitted_interaction_then_quiesces(self):
        session, coordinator, _, events = self.make(); session.start()
        coordinator.lifecycle.set(VoiceState.CAPTURE_PROCESSING)
        session.activation_received("inactive")
        self.assertFalse(session.quiescent)
        coordinator.lifecycle.set(VoiceState.LISTENING)
        self.assertTrue(session.quiescent)
        self.assertIn("[VoiceSession] waiting for admitted interaction to finish", events)

    def test_active_wakes_quiescent_voice(self):
        session, coordinator, timers, _ = self.make(); session.start(); timers[-1].callback()
        session.activation_received("active")
        self.assertEqual(coordinator.reactivated, 1)
        self.assertTrue(session.admitting_interactions)

    def test_semantic_ingress_remains_available_while_quiescent(self):
        session, coordinator, timers, _ = self.make(); session.start(); timers[-1].callback()
        ingress = VoiceSemanticIngress(session.activation_received)
        self.assertTrue(ingress.handle_event(installation_activation("test", "active", id="wake")))
        self.assertEqual(coordinator.reactivated, 1)

    def test_button_debounces_one_physical_press(self):
        presses, now = [], [0.0]
        button = InteractionButton(17, lambda: presses.append("button"), debounce_seconds=.4,
            input_factory=FakeInput, monotonic=lambda: now[0], emit=lambda _: None)
        self.assertTrue(button.handle_press()); now[0] = .2
        self.assertFalse(button.handle_press()); now[0] = .5
        self.assertTrue(button.handle_press())
        self.assertEqual(presses, ["button", "button"])
        button.close()


if __name__ == "__main__":
    unittest.main()
