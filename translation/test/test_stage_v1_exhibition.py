import importlib
import sys
import unittest


class ExhibitionCompositionTests(unittest.TestCase):
    def test_default_cli_is_exhibition_not_oracle_demonstrator(self):
        app = importlib.import_module("voice_rack_test_v0_7")
        original = sys.argv
        try:
            sys.argv = ["voice_rack_test_v0_7.py"]
            args = app.parse_arguments()
            self.assertFalse(args.oracle)
        finally:
            sys.argv = original

    def test_oracle_remains_an_explicit_legacy_compatibility_option(self):
        app = importlib.import_module("voice_rack_test_v0_7")
        original = sys.argv
        try:
            sys.argv = ["voice_rack_test_v0_7.py", "--oracle"]
            self.assertTrue(app.parse_arguments().oracle)
        finally:
            sys.argv = original


if __name__ == "__main__":
    unittest.main()
