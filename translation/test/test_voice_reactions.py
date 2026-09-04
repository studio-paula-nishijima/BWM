import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "translation" / "src"))

from runtime.clock import SimulatedClock
from runtime.session import PlaybackSessionRuntime
from shared.messaging.events import whisper_state
from shared.messaging.topics import TopicNamespace
from runtime.mqtt_adapter import TranslationMQTTAdapter
from runtime.voice_reactions import prepare_voice_reactions


def event(at, target="base"):
    return {"type": "solenoid", "playback_time": at, "target": target, "duration": .1}


class Dispatcher:
    def __init__(self): self.events, self.quiesce_count = [], 0
    def dispatch(self, item): self.events.append(item)
    def quiesce(self): self.quiesce_count += 1


class VoiceReactionTests(unittest.TestCase):
    def test_configuration_validation_rejects_invalid_types_and_targets_at_startup(self):
        policies = {"voice_default": {"mode": "fixed", "strategy": "reaction"}}
        with self.assertRaisesRegex(ValueError, "unknown reaction type"):
            prepare_voice_reactions({"reaction": {"type": "unknown"}}, policies, "voice_default", ["a"])
        with self.assertRaisesRegex(ValueError, "unknown target"):
            prepare_voice_reactions({"reaction": {"type": "override_sequence", "phases": [
                {"type": "sequence", "targets": ["missing"], "spacing_seconds": 0}]}},
                policies, "voice_default", ["a"])

    def test_voice_preparation_ignores_base_modulation_policies(self):
        strategies = {
            "cascade": {"type": "cascade"},
            "reaction": {"type": "repeat_transform", "duration_seconds": 1,
                         "repeat_count": 2, "tap_spacing_seconds": .1},
        }
        policies = {"default": {"mode": "fixed", "strategy": "cascade"},
                    "voice_default": {"mode": "fixed", "strategy": "reaction"},
                    "voice_band_1": {"mode": "fixed", "strategy": "reaction"}}
        prepared, _ = prepare_voice_reactions(strategies, policies, "voice_default", ["a"],
                                               additional_policy_names=("voice_band_1",))
        self.assertEqual(prepared["cascade"]["type"], "cascade")
    def make_runtime(self, strategy, events):
        self.clock, self.dispatcher = SimulatedClock(), Dispatcher()
        config = {"strategies": {"reaction": strategy},
                  "policies": {"voice_default": {"mode": "fixed", "strategy": "reaction"}}}
        runtime = PlaybackSessionRuntime(lambda: events, self.clock, self.dispatcher, 30,
            reaction_policy_config=config, whisper_interaction_config={"enabled": True,
                "trigger_state": "capture_processing", "reaction_policy": "voice_default"},
            reaction_targets=["n", "s", "e", "west", "north", "east", "south", "a", "b", "base"])
        topics = TopicNamespace()
        adapter = TranslationMQTTAdapter(runtime, topics.installation_activation, topics.whisper_state)
        runtime.activate()
        adapter.handle(topics.whisper_state, whisper_state("whisper_pi", "listening"))
        self.assertEqual(adapter.handle(topics.whisper_state, whisper_state("whisper_pi", "capture_processing")), "triggered")
        return runtime, adapter, topics.whisper_state

    def test_a_simultaneous_then_sequence_override_uses_quiet_gap_and_resumes(self):
        strategy = {"type": "override_sequence", "initial_quiet_gap_seconds": .5,
                    "phases": [{"type": "simultaneous", "targets": "all"},
                               {"type": "wait", "duration_seconds": .5},
                               {"type": "sequence", "targets": ["n", "s", "e"], "spacing_seconds": .2},
                               {"type": "wait", "duration_seconds": 1.0}]}
        # The admitted pulse at t=0 makes the configured quiet gap meaningful.
        self.clock, self.dispatcher = SimulatedClock(), Dispatcher()
        config = {"strategies": {"reaction": strategy}, "policies": {"voice_default": {"mode": "fixed", "strategy": "reaction"}}}
        runtime = PlaybackSessionRuntime(lambda: [event(.25), event(1), event(2.5)], self.clock, self.dispatcher, 30,
            reaction_policy_config=config, whisper_interaction_config={"enabled": True, "trigger_state": "capture_processing", "reaction_policy": "voice_default"},
            reaction_targets=["n", "s", "e"])
        runtime.activate(); runtime.safety.dispatch(event(-1, "prior"))
        topics = TopicNamespace(); adapter = TranslationMQTTAdapter(runtime, topics.installation_activation, topics.whisper_state)
        adapter.handle(topics.whisper_state, whisper_state("whisper_pi", "listening")); adapter.handle(topics.whisper_state, whisper_state("whisper_pi", "capture_processing"))
        self.clock.advance(.25); runtime.step(); self.assertEqual([x["target"] for x in self.dispatcher.events], ["prior"])
        self.clock.advance(.25); runtime.step(); self.assertEqual([x["target"] for x in self.dispatcher.events], ["prior", "n", "s", "e"])
        self.clock.advance(.5); runtime.step(); self.assertEqual(self.dispatcher.events[-1]["target"], "n")
        self.clock.advance(.2); runtime.step(); self.assertEqual(self.dispatcher.events[-1]["target"], "s")
        self.clock.advance(.2); runtime.step(); self.assertEqual(self.dispatcher.events[-1]["target"], "e")
        self.clock.advance(1.1); runtime.step()
        self.assertEqual(self.dispatcher.events[-1]["target"], "base")  # current score position; no catch-up
        self.assertFalse(runtime.engine.is_paused)
        self.assertFalse(runtime.external_reaction_busy)

    def test_cascade_reaction_is_configured_and_non_pausing(self):
        strategy = {"type": "override_sequence", "initial_quiet_gap_seconds": .5,
                    "phases": [{"type": "sequence", "targets": ["west", "north", "east", "south"], "spacing_seconds": .3},
                               {"type": "wait", "duration_seconds": 1.0}]}
        runtime, adapter, topic = self.make_runtime(strategy, [event(.25), event(3)])
        adapter.handle(topic, whisper_state("whisper_pi", "response_displayed"))
        self.assertEqual(adapter.handle(topic, whisper_state("whisper_pi", "capture_processing")), "ignored_busy")
        self.clock.advance(.5); runtime.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["west"])
        for expected in ("north", "east", "south"):
            self.clock.advance(.3); runtime.step(); self.assertEqual(self.dispatcher.events[-1]["target"], expected)
        self.clock.advance(1.1); runtime.step()
        self.assertFalse(runtime.external_reaction_busy)
        self.assertFalse(runtime.engine.is_paused)

    def test_phase_edits_change_sequence_order_and_spacing_without_code_changes(self):
        strategy = {"type": "override_sequence", "initial_quiet_gap_seconds": 0,
                    "phases": [{"type": "sequence", "targets": ["east", "west", "north"], "spacing_seconds": .4}]}
        runtime, _, _ = self.make_runtime(strategy, [event(10)])
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["east"])
        self.clock.advance(.39); runtime.step(); self.assertEqual(len(self.dispatcher.events), 1)
        self.clock.advance(.01); runtime.step(); self.assertEqual(self.dispatcher.events[-1]["target"], "west")
        self.clock.advance(.4); runtime.step(); self.assertEqual(self.dispatcher.events[-1]["target"], "north")

    def test_c_triple_tap_transforms_only_its_window(self):
        strategy = {"type": "repeat_transform", "repeat_count": 3, "tap_spacing_seconds": .2, "duration_seconds": 3.0}
        runtime, adapter, topic = self.make_runtime(strategy, [event(0, "a"), event(1, "b"), event(3.1, "c")])
        adapter.handle(topic, whisper_state("whisper_pi", "response_displayed")); self.assertEqual(adapter.handle(topic, whisper_state("whisper_pi", "capture_processing")), "ignored_busy")
        runtime.step(); self.clock.advance(.2); runtime.step(); self.clock.advance(.2); runtime.step()
        self.clock.advance(.6); runtime.step(); self.clock.advance(.2); runtime.step(); self.clock.advance(.2); runtime.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["a", "a", "a", "b", "b", "b"])
        self.clock.advance(2.1); runtime.step()
        self.assertEqual(self.dispatcher.events[-1]["target"], "c")
        self.assertFalse(runtime.external_reaction_busy)

    def test_d_double_tap_transforms_only_its_window_and_teardown_cancels(self):
        strategy = {"type": "repeat_transform", "repeat_count": 2, "tap_spacing_seconds": .2, "duration_seconds": 4.0}
        runtime, adapter, topic = self.make_runtime(strategy, [event(0, "a"), event(4.1, "b")])
        adapter.handle(topic, whisper_state("whisper_pi", "response_displayed")); self.assertEqual(adapter.handle(topic, whisper_state("whisper_pi", "capture_processing")), "ignored_busy")
        runtime.step(); self.clock.advance(.2); runtime.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["a", "a"])
        self.assertTrue(all(decision.accepted for decision in runtime.safety.decisions))
        self.clock.advance(3.9); runtime.step()
        self.assertEqual(self.dispatcher.events[-1]["target"], "b")
        self.assertFalse(runtime.external_reaction_busy)
        runtime.deactivate()
        self.assertFalse(runtime.external_reaction_busy)
        self.assertEqual(runtime.modulation.pending_count, 0)
        self.assertEqual(self.dispatcher.quiesce_count, 1)


if __name__ == "__main__":
    unittest.main()
