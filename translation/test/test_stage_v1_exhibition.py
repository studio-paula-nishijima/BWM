import importlib
import sys
import unittest


class ExhibitionCompositionTests(unittest.TestCase):
    def test_default_cli_is_exhibition_not_oracle_demonstrator(self):
        app = importlib.import_module("whisper_runtime")
        original = sys.argv
        try:
            sys.argv = ["whisper_runtime.py"]
            args = app.parse_arguments()
            self.assertFalse(args.oracle)
        finally:
            sys.argv = original

    def test_oracle_remains_an_explicit_legacy_compatibility_option(self):
        app = importlib.import_module("whisper_runtime")
        original = sys.argv
        try:
            sys.argv = ["whisper_runtime.py", "--oracle"]
            self.assertTrue(app.parse_arguments().oracle)
        finally:
            sys.argv = original


if __name__ == "__main__":
    unittest.main()
