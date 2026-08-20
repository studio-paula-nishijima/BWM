import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runtime.clock import SimulatedClock
from runtime.modulation import RuntimeModulationEngine
from runtime.playback import PlaybackEngine
from runtime.session import PlaybackSessionRuntime


def event(at, target="a", duration=0.1):
    return {"type": "solenoid", "playback_time": at, "target": target, "duration": duration,
            "metadata": {"source": "test"}}


class Dispatcher:
    def __init__(self): self.events = []
    def dispatch(self, item): self.events.append(item)


class RuntimeModulationTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.dispatcher = SimulatedClock(), Dispatcher()

    def make_engine(self, events):
        modulation = RuntimeModulationEngine(self.clock, self.dispatcher)
        engine = PlaybackEngine(events, self.clock, due_event_handler=modulation.process)
        modulation.bind_playback_control(engine)
        engine.start()
        return engine, modulation

    def test_pass_through_is_ordered_and_does_not_mutate_score(self):
        score = [event(0, "a"), event(1, "b")]
        original = deepcopy(score)
        engine, modulation = self.make_engine(score)
        engine.step(); self.clock.advance(1); engine.step(); modulation.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["a", "b"])
        self.assertEqual(score, original)

    def test_suppression_and_later_base_events(self):
        engine, modulation = self.make_engine([event(0, "a"), event(1, "b")])
        modulation.trigger("suppress", targets=["a"], active_for=0.5,
                           timeline_policy="override_while_continuing")
        engine.step(); self.clock.advance(1); engine.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["b"])

    def test_replacement_can_emit_many_events(self):
        engine, modulation = self.make_engine([event(0, "a")])
        modulation.trigger("replace", base_treatment="replace",
                           replacement_events=[event(0, "x"), event(0, "y")])
        engine.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["x", "y"])

    def test_multitap_delays_are_deterministic(self):
        engine, modulation = self.make_engine([event(0, "a")])
        modulation.trigger("multi_tap", repeat_count=3, inter_tap_delay=1,
                           base_treatment="suppress")
        engine.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["a"])
        self.clock.advance(1); modulation.step()
        self.clock.advance(1); modulation.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["a", "a", "a"])

    def test_cascade_uses_configured_non_six_target_order(self):
        score = [event(0, "source")]
        original = deepcopy(score)
        engine, modulation = self.make_engine(score)
        modulation.trigger("cascade", ordered_targets=["north", "east", "west", "south"],
                           inter_step_delay=0.25, base_treatment="suppress")
        engine.step()
        for _ in range(3):
            self.clock.advance(.25); modulation.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events],
                         ["north", "east", "west", "south"])
        self.assertEqual(score, original)

    def test_overlay_does_not_hold_base_score(self):
        engine, modulation = self.make_engine([event(0, "a"), event(.5, "b")])
        modulation.trigger("multi_tap", repeat_count=2, inter_tap_delay=1)
        engine.step(); self.clock.advance(.5); engine.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["a", "a", "b"])
        self.clock.advance(.5); modulation.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["a", "a", "b", "a"])

    def test_override_continues_logical_time_and_then_releases(self):
        engine, modulation = self.make_engine([event(0, "a"), event(1, "b"), event(2, "c")])
        modulation.trigger("suppress", active_for=1.5, timeline_policy="override_while_continuing")
        engine.step(); self.clock.advance(1); engine.step(); self.clock.advance(1); engine.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["c"])

    def test_pause_and_fill_freezes_playback_then_resumes(self):
        engine, modulation = self.make_engine([event(0, "a"), event(1, "b")])
        modulation.trigger("multi_tap", repeat_count=2, inter_tap_delay=2,
                           base_treatment="suppress", timeline_policy="pause_and_fill")
        engine.step()
        self.assertTrue(engine.is_paused)
        self.clock.advance(1); engine.step(); modulation.step()
        self.assertEqual(engine.event_index, 1)
        self.clock.advance(1); modulation.step()
        self.assertTrue(engine.is_running)
        self.clock.advance(1); engine.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["a", "a", "b"])

    def test_timeout_and_cancellation_clear_reaction_state(self):
        source = [event(0, "a"), event(10, "b")]
        runtime = PlaybackSessionRuntime(lambda: source, self.clock, self.dispatcher, 2)
        runtime.activate()
        runtime.trigger("multi_tap", repeat_count=3, inter_tap_delay=1,
                        base_treatment="suppress", timeline_policy="pause_and_fill")
        runtime.step(); self.assertTrue(runtime.engine.is_paused)
        self.clock.advance(2); runtime.step()
        self.assertFalse(runtime.is_active)
        self.assertEqual(runtime.modulation.pending_count, 0)
        self.clock.advance(10); runtime.step()
        self.assertEqual([x["target"] for x in self.dispatcher.events], ["a"])
        runtime.activate()
        self.assertFalse(runtime.engine.is_paused)
        self.assertIsNone(runtime.modulation.active_strategy)

    def test_each_activation_builds_a_clean_fresh_session(self):
        selections = [[event(0, "first")], [event(0, "second")]]
        runtime = PlaybackSessionRuntime(lambda: selections.pop(0), self.clock,
                                         self.dispatcher, 10)
        runtime.activate(); runtime.step()
        self.assertFalse(runtime.is_active)
        runtime.activate(); runtime.step()
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["first", "second"])


if __name__ == "__main__":
    unittest.main()
