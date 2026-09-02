import importlib
import unittest


class VoiceRackShutdownTests(unittest.TestCase):
    def test_shutdown_guard_allows_only_one_cleanup(self):
        app = importlib.import_module("whisper_runtime")
        previous = app.shutdown_started
        try:
            app.shutdown_started = False
            self.assertTrue(app._begin_shutdown())
            self.assertFalse(app._begin_shutdown())
        finally:
            app.shutdown_started = previous


if __name__ == "__main__":
    unittest.main()
