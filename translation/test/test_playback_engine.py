import sys
import unittest
from pathlib import Path

TRANSLATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRANSLATION_ROOT / "src"))

from runtime.clock import SimulatedClock
from runtime.playback import PlaybackEngine


class Dispatcher:
    def __init__(self): self.events = []
    def dispatch(self, event): self.events.append(event)


class PlaybackEngineTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.dispatcher = SimulatedClock(), Dispatcher()
        self.events = [{"playback_time": t, "target": name} for t, name in
                       [(0.0, "first"), (1.0, "second"), (1.0, "third"), (3.0, "fourth")]]
        self.engine = PlaybackEngine(self.events, self.clock, self.dispatcher)

    def test_due_events_dispatch_once_in_score_order(self):
        self.engine.start()
        self.assertEqual(self.engine.step(), 1)
        self.clock.advance(1)
        self.assertEqual(self.engine.step(), 2)
        self.clock.advance(3)
        self.assertEqual(self.engine.step(), 1)
        self.assertTrue(self.engine.is_complete)
        self.assertEqual([event["target"] for event in self.dispatcher.events],
                         ["first", "second", "third", "fourth"])

    def test_stop_prevents_future_dispatch(self):
        self.engine.start()
        self.engine.stop()
        self.clock.advance(4)
        self.assertEqual(self.engine.step(), 0)
        self.assertEqual(self.engine.state, PlaybackEngine.STOPPED)


if __name__ == "__main__":
    unittest.main()
