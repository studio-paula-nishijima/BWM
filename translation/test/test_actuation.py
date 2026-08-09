import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from actuation.runtime import resolve_actuation_enabled, request_for_emitted_trigger


class ActuationTests(unittest.TestCase):
    def test_source_defaults_and_explicit_overrides(self):
        self.assertTrue(resolve_actuation_enabled(wav_path=None))
        self.assertFalse(resolve_actuation_enabled(wav_path="example.wav"))
        self.assertFalse(resolve_actuation_enabled(wav_path=None, no_actuation=True))
        self.assertTrue(resolve_actuation_enabled(wav_path="example.wav", enable_actuation=True))
        with self.assertRaises(ValueError):
            resolve_actuation_enabled(wav_path=None, enable_actuation=True, no_actuation=True)

    def test_only_real_emitted_trigger_requests_hardware(self):
        class Recorder:
            def __init__(self): self.requests = 0
            def actuate(self):
                self.requests += 1
                return {"requested": True, "started": True}

        recorder = Recorder()
        self.assertIsNone(request_for_emitted_trigger(emitted_trigger=False, controller=recorder))
        self.assertEqual(recorder.requests, 0)
        self.assertTrue(request_for_emitted_trigger(emitted_trigger=True, controller=recorder)["started"])
        self.assertEqual(recorder.requests, 1)


if __name__ == "__main__":
    unittest.main()
