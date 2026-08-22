import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRANSLATION = ROOT / "translation"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TRANSLATION / "src"))

from runtime.clock import SimulatedClock
from runtime.mqtt_adapter import TranslationMQTTAdapter
from runtime.session import PlaybackSessionRuntime
from shared.messaging.events import SemanticEvent, voice_state
from shared.messaging.topics import TopicNamespace


def event(at=10, target="base"):
    return {"type": "solenoid", "playback_time": at, "target": target, "duration": .1}


class Dispatcher:
    def __init__(self):
        self.events, self.quiesce_count = [], 0
    def dispatch(self, item): self.events.append(item)
    def quiesce(self): self.quiesce_count += 1


def policy():
    return {"strategies": {
        "voice_tap": {"type": "repeat_transform", "repeat_count": 3,
                      "tap_spacing_seconds": 1, "duration_seconds": 2},
        "voice_cascade": {"type": "override_sequence", "phases": [
                          {"type": "sequence", "targets": ["one", "two"], "spacing_seconds": 1}]}},
            "policies": {"voice_default": {"mode": "fixed", "strategy": "voice_tap"}}}


class VoiceStateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.dispatcher = SimulatedClock(), Dispatcher()
        self.runtime = PlaybackSessionRuntime(lambda: [event(0, "voice"), event(10, "base")], self.clock, self.dispatcher, 20,
            reaction_policy_config=policy(), voice_interaction_config={"enabled": True,
                "trigger_state": "capture_processing", "reaction_policy": "voice_default"},
            reaction_targets=["voice", "one", "two", "base"])
        topics = TopicNamespace()
        self.adapter = TranslationMQTTAdapter(self.runtime, topics.installation_activation, topics.voice_state)
        self.topic = topics.voice_state

    def send(self, state, identifier=None):
        return self.adapter.handle(self.topic, voice_state("voice_pi", state, id=identifier) if identifier
                                   else voice_state("voice_pi", state))

    def test_shared_voice_state_validation_and_topic(self):
        self.assertEqual(self.topic, "bwm/voice/state")
        self.assertEqual(voice_state("voice_pi", "listening").event_type, "voice.state")
        self.assertEqual(self.adapter.handle(self.topic, SemanticEvent("voice.state", "voice_pi",
                         {"state": "low_level_detector"})), "rejected_invalid")

    def test_transition_is_configurable_and_idle_does_not_activate(self):
        self.assertEqual(self.send("capture_processing"), "ignored_inactive")
        self.assertFalse(self.runtime.is_active)
        self.runtime.activate()
        self.assertEqual(self.send("listening"), "observed")
        self.assertEqual(self.send("capture_processing"), "triggered")
        self.runtime.step()
        self.assertEqual(self.runtime.voice_state, "capture_processing")
        self.assertEqual(len(self.dispatcher.events), 1)
        self.assertEqual(self.send("capture_processing"), "observed_no_transition")

    def test_configured_other_trigger_state_needs_no_code_change(self):
        self.runtime._voice_interaction["trigger_state"] = "whisper_detected"
        self.runtime.activate()
        self.assertEqual(self.send("listening"), "observed")
        self.assertEqual(self.send("capture_processing"), "observed")
        self.assertEqual(self.send("whisper_detected"), "triggered")

    def test_voice_policy_uses_only_its_configured_weighted_candidates(self):
        class LastChoice:
            def choices(self, names, weights, k):
                self.names, self.weights = names, weights
                return [names[-1]]
        configured = policy()
        configured["policies"]["voice_default"] = {"mode": "weighted",
                                                      "choices": {"voice_tap": 1, "voice_cascade": 3}}
        runtime = PlaybackSessionRuntime(lambda: [event()], self.clock, self.dispatcher, 20,
            reaction_policy_config=configured, rng=LastChoice(), voice_interaction_config={"enabled": True,
                "trigger_state": "capture_processing", "reaction_policy": "voice_default"},
            reaction_targets=["voice", "one", "two", "base"])
        adapter = TranslationMQTTAdapter(runtime, TopicNamespace().installation_activation, self.topic)
        runtime.activate()
        adapter.handle(self.topic, voice_state("voice_pi", "listening"))
        self.assertEqual(adapter.handle(self.topic, voice_state("voice_pi", "capture_processing")), "triggered")
        self.assertEqual(self.dispatcher.events[0]["target"], "one")

    def test_duplicate_id_is_filtered_before_transition(self):
        self.runtime.activate()
        self.assertEqual(self.send("listening", "one"), "observed")
        self.assertEqual(self.send("capture_processing", "two"), "triggered")
        self.runtime.step()
        self.assertEqual(self.send("capture_processing", "two"), "ignored_duplicate")
        self.assertEqual(len(self.dispatcher.events), 1)

    def test_busy_drops_not_queues_and_clears_after_final_output(self):
        self.runtime.activate()
        self.send("listening"); self.assertEqual(self.send("capture_processing"), "triggered"); self.runtime.step()
        self.assertTrue(self.runtime.external_reaction_busy)
        self.send("response_displayed"); self.assertEqual(self.send("capture_processing"), "ignored_busy")
        self.clock.advance(1); self.runtime.step()
        self.assertTrue(self.runtime.external_reaction_busy)
        self.clock.advance(1); self.runtime.step()
        self.assertFalse(self.runtime.external_reaction_busy)
        self.send("listening"); self.assertEqual(self.send("capture_processing"), "triggered")
        self.assertEqual(len(self.dispatcher.events), 3)  # first transformed base event only

    def test_full_chain_safety_and_non_pausing_base_playback(self):
        self.runtime.activate()
        self.send("listening"); self.send("capture_processing")
        self.runtime.step()
        self.assertFalse(self.runtime.engine.is_paused)
        self.clock.advance(1); self.runtime.step()
        # The score is still running and its ordinary due event reaches safety/router.
        self.clock.advance(9); self.runtime.step()
        # At a coarse runtime tick the due base score event is handled before
        # modulation drains its due artistic delay; neither path is blocked.
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["voice", "voice", "base", "voice"])
        self.assertEqual(self.runtime.safety.observations("voice")["accepted_count"], 3)
        self.assertFalse(self.runtime.engine.is_paused)

    def test_teardown_cancels_pending_external_work_and_busy(self):
        self.runtime.activate()
        self.send("listening"); self.send("capture_processing")
        self.runtime.step()
        self.assertTrue(self.runtime.external_reaction_busy)
        self.runtime.deactivate()
        self.assertFalse(self.runtime.external_reaction_busy)
        self.assertEqual(self.runtime.modulation.pending_count, 0)
        self.clock.advance(5); self.runtime.step()
        self.assertEqual(len(self.dispatcher.events), 1)
        self.assertEqual(self.dispatcher.quiesce_count, 1)


if __name__ == "__main__":
    unittest.main()
