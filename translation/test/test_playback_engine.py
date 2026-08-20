import sys
import unittest
from pathlib import Path


TRANSLATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRANSLATION_ROOT / "src"))

from runtime.clock import SimulatedClock
from runtime.playback import PlaybackEngine


def event(playback_time, target):
    return {"playback_time": playback_time, "target": target}


class FakeDispatcher:
    def __init__(self):
        self.events = []

    def dispatch(self, due_event):
        self.events.append(due_event)


class PlaybackEngineTests(unittest.TestCase):
    def setUp(self):
        self.clock = SimulatedClock()
        self.dispatcher = FakeDispatcher()
        self.events = [event(0.0, "first"), event(1.0, "second"), event(1.0, "third"), event(3.0, "fourth")]
        self.engine = PlaybackEngine(self.events, self.clock, self.dispatcher)

    def test_initial_state_does_not_dispatch_before_start(self):
        self.assertEqual(self.engine.state, PlaybackEngine.READY)
        self.assertFalse(self.engine.is_running)
        self.assertEqual(self.engine.step(), 0)
        self.assertEqual(self.dispatcher.events, [])

    def test_due_events_dispatch_in_score_order(self):
        self.engine.start()
        self.assertEqual(self.engine.step(), 1)
        self.clock.advance(0.999)
        self.assertEqual(self.engine.step(), 0)
        self.clock.advance(0.001)
        self.assertEqual(self.engine.step(), 2)
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["first", "second", "third"])

    def test_single_step_dispatches_all_overdue_events_exactly_once(self):
        self.engine.start()
        self.clock.advance(4.0)
        self.assertEqual(self.engine.step(), 4)
        self.assertTrue(self.engine.is_complete)
        self.assertEqual(self.engine.event_index, self.engine.event_count)
        self.assertEqual(self.engine.step(), 0)
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["first", "second", "third", "fourth"])

    def test_stop_prevents_future_dispatch_without_touching_dispatcher(self):
        self.engine.start()
        self.engine.stop()
        self.clock.advance(4.0)
        self.assertEqual(self.engine.state, PlaybackEngine.STOPPED)
        self.assertEqual(self.engine.step(), 0)
        self.assertEqual(self.dispatcher.events, [])

    def test_engine_uses_clock_relative_to_start(self):
        self.clock.advance(10.0)
        self.engine.start()
        self.clock.advance(1.0)
        self.engine.step()
        self.assertEqual([item["target"] for item in self.dispatcher.events], ["first", "second", "third"])

    def test_stage1_dispatch_equivalence_for_shared_and_crossed_times(self):
        """Mirror 62f980c's ordered target-time waits at each clock observation."""
        observed_times = [0.0, 0.5, 1.0, 3.5]
        expected = []
        next_index = 0
        for elapsed in observed_times:
            while (
                next_index < len(self.events)
                and self.events[next_index]["playback_time"] <= elapsed
            ):
                expected.append(self.events[next_index])
                next_index += 1

        self.engine.start()
        for elapsed in observed_times:
            self.clock.t = elapsed
            self.engine.step()

        self.assertEqual(self.dispatcher.events, expected)
        self.assertTrue(self.engine.is_complete)


if __name__ == "__main__":
    unittest.main()
