import random
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from runtime.clock import SimulatedClock
from runtime.modulation import RuntimeModulationEngine
from runtime.playback import PlaybackEngine
from runtime.reaction_policy import ReactionPolicy
from runtime.safety import RuntimeSafety
from runtime.session import PlaybackSessionRuntime


def event(at=0, target="a", duration=.15):
    return {"type": "solenoid", "playback_time": at, "target": target, "duration": duration}


class Dispatcher:
    def __init__(self): self.events = []
    def dispatch(self, item): self.events.append(item)


def emergency_config():
    return {"enabled": True, "emergency": {
        "max_pulse_duration": {"enabled": True, "seconds": 5, "action": "reject"},
        "runaway_rate": {"enabled": True, "window_seconds": 5, "max_events": 40},
        "extreme_duty": {"enabled": False, "window_seconds": 10, "max_fraction": .95},
    }, "thermal": {"enabled": True, "enforce": True, "reference_pulse_seconds": .15,
                    "cooling_time_constant_seconds": 90, "emergency_load_threshold": 100}}


class RuntimeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.dispatcher = SimulatedClock(), Dispatcher()
        self.safety = RuntimeSafety(self.clock, self.dispatcher, emergency_config())

    def test_normal_base_cascade_and_multitap_pass_unchanged(self):
        modulation = RuntimeModulationEngine(self.clock, self.safety)
        engine = PlaybackEngine([event()], self.clock, due_event_handler=modulation.process)
        modulation.bind_playback_control(engine); engine.start()
        modulation.trigger("multi_tap", repeat_count=3, inter_tap_delay=.1, base_treatment="suppress")
        engine.step()
        self.clock.advance(.1); modulation.step(); self.clock.advance(.1); modulation.step()
        self.assertEqual([item["duration"] for item in self.dispatcher.events], [.15, .15, .15])
        self.assertEqual(self.safety.observations("a")["rejected_count"], 0)

    def test_normal_cascade_is_far_below_permissive_thermal_cutoff(self):
        modulation = RuntimeModulationEngine(self.clock, self.safety)
        engine = PlaybackEngine([event(target="source")], self.clock, due_event_handler=modulation.process)
        modulation.bind_playback_control(engine); engine.start()
        modulation.trigger("cascade", ordered_targets=["north", "east", "west"],
                           inter_step_delay=.1, base_treatment="suppress")
        engine.step(); self.clock.advance(.1); modulation.step(); self.clock.advance(.1); modulation.step()
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["north", "east", "west"])
        self.assertTrue(all(decision.accepted for decision in self.safety.decisions))

    def test_twenty_hz_runaway_is_rejected_per_target(self):
        for _ in range(100):
            self.safety.dispatch(event(target="a"))
            self.clock.advance(.05)
        self.safety.dispatch(event(target="b"))
        a = self.safety.observations("a")
        self.assertGreater(a["rejected_count"], 0)
        self.assertEqual(self.safety.observations("b")["accepted_count"], 1)
        self.assertEqual(self.safety.decisions[-2].reason, "runaway_event_rate")

    def test_long_pulse_is_visible_and_rejected(self):
        decision = self.safety.dispatch(event(duration=20))
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "max_pulse_duration")
        self.assertEqual(self.dispatcher.events, [])

    def test_history_persists_across_sessions_and_uses_runtime_time(self):
        runtime = PlaybackSessionRuntime(lambda: [event()], self.clock, self.dispatcher, 10,
                                         safety_config=emergency_config())
        runtime.activate(); runtime.step(); runtime.deactivate()
        self.clock.advance(1); runtime.activate()
        self.assertEqual(runtime.safety.observations("a")["recent_accepted_count"], 1)

    def test_pause_and_fill_keeps_physical_observation_time_moving(self):
        modulation = RuntimeModulationEngine(self.clock, self.safety)
        engine = PlaybackEngine([event(), event(1, "b")], self.clock, due_event_handler=modulation.process)
        modulation.bind_playback_control(engine); engine.start()
        modulation.trigger("multi_tap", repeat_count=2, inter_tap_delay=1,
                           base_treatment="suppress", timeline_policy="pause_and_fill")
        engine.step(); self.assertTrue(engine.is_paused)
        self.clock.advance(1); modulation.step()
        self.assertEqual(engine.elapsed_time, 0)
        self.assertEqual(self.safety.observations("a")["last_accepted_at"], 1)

    def test_normal_pulse_adds_normalized_thermal_load(self):
        self.safety.dispatch(event(duration=.15))
        self.assertEqual(self.safety.observations("a")["thermal_load"], 1.0)

    def test_thermal_load_decays_with_fake_monotonic_time(self):
        self.safety.dispatch(event(duration=.15))
        self.clock.advance(90)
        self.assertAlmostEqual(self.safety.observations("a")["thermal_load"], math.exp(-1))

    def test_thermal_load_accumulates_and_targets_are_independent(self):
        self.safety.dispatch(event(target="a", duration=.15)); self.safety.dispatch(event(target="a", duration=.30))
        self.safety.dispatch(event(target="b", duration=.15))
        self.assertEqual(self.safety.observations("a")["thermal_load"], 3.0)
        self.assertEqual(self.safety.observations("b")["thermal_load"], 1.0)

    def test_thermal_load_continues_during_pause_and_fill(self):
        modulation = RuntimeModulationEngine(self.clock, self.safety)
        engine = PlaybackEngine([event(), event(1, "b")], self.clock, due_event_handler=modulation.process)
        modulation.bind_playback_control(engine); engine.start()
        modulation.trigger("multi_tap", repeat_count=2, inter_tap_delay=10,
                           base_treatment="suppress", timeline_policy="pause_and_fill")
        engine.step(); self.assertTrue(engine.is_paused)
        self.clock.advance(10); modulation.step()
        self.assertEqual(engine.elapsed_time, 0)
        self.assertAlmostEqual(self.safety.observations("a")["thermal_load"], 1 + math.exp(-10 / 90))

    def test_thermal_cutoff_rejects_only_extreme_sustained_workload(self):
        config = emergency_config()
        config["thermal"].update({"enforce": True, "emergency_load_threshold": 3.0})
        safety = RuntimeSafety(self.clock, self.dispatcher, config)
        for _ in range(3):
            self.assertTrue(safety.dispatch(event(duration=.15)).accepted)
        decision = safety.dispatch(event(duration=.15))
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "thermal_load")


class ReactionPolicyTests(unittest.TestCase):
    def test_modes_and_category_fallback_are_deterministic(self):
        strategies = {"cascade": {"type": "cascade"}, "tap": {"type": "multi_tap"}}
        policy = ReactionPolicy(strategies, {"default": {"mode": "weighted", "choices": {"cascade": 1, "tap": 1}},
                                             "presence": {"mode": "fixed", "strategy": "tap"}}, random.Random(4))
        self.assertEqual(policy.select("presence")[0], "tap")
        self.assertIn(policy.select("unknown")[0], strategies)
        self.assertIn(ReactionPolicy(strategies, {"default": {"mode": "uniform", "choices": ["tap"]}}).select()[0], strategies)

    def test_invalid_configuration_fails_clearly(self):
        with self.assertRaises(ValueError):
            ReactionPolicy({}, {"default": {"mode": "fixed", "strategy": "missing"}})
        with self.assertRaises(ValueError):
            ReactionPolicy({"a": {}}, {"default": {"mode": "weighted", "choices": {"a": 0}}})

    def test_selected_strategy_still_flows_through_safety(self):
        clock, dispatcher = SimulatedClock(), Dispatcher()
        runtime = PlaybackSessionRuntime(lambda: [event()], clock, dispatcher, 10,
            safety_config=emergency_config(), reaction_policy_config={
                "strategies": {"triple": {"type": "multi_tap", "repeat_count": 3, "inter_tap_delay": .1,
                                               "base_treatment": "suppress"}},
                "policies": {"default": {"mode": "fixed", "strategy": "triple"}}})
        runtime.activate(); runtime.trigger_reaction(); runtime.step()
        clock.advance(.1); runtime.step(); clock.advance(.1); runtime.step()
        self.assertEqual(len(dispatcher.events), 3)
        self.assertEqual(runtime.safety.observations("a")["accepted_count"], 3)
