import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audio.arecord_source import ArecordSource


class FakePipe:
    def __init__(self): self.closed = False
    def close(self): self.closed = True


class FakeProcess:
    def __init__(self, timeout=False):
        self.stdout, self.timeout = FakePipe(), timeout
        self.terminated = self.killed = self.waits = 0
    def poll(self): return None
    def terminate(self): self.terminated += 1
    def wait(self, timeout):
        self.waits += 1
        if self.timeout and self.waits == 1:
            import subprocess
            raise subprocess.TimeoutExpired("arecord", timeout)
    def kill(self): self.killed += 1


class ArecordSourceCloseTests(unittest.TestCase):
    def test_close_waits_for_arecord_and_closes_stdout(self):
        source, process = ArecordSource("plughw:2,0", 16000, 480), FakeProcess()
        source.proc = process
        source.close()
        self.assertIsNone(source.proc)
        self.assertEqual(process.terminated, 1)
        self.assertEqual(process.waits, 1)
        self.assertTrue(process.stdout.closed)

    def test_close_kills_a_process_that_does_not_exit(self):
        source, process = ArecordSource("plughw:2,0", 16000, 480), FakeProcess(timeout=True)
        source.proc = process
        source.close()
        self.assertEqual(process.killed, 1)
        self.assertEqual(process.waits, 2)
        self.assertTrue(process.stdout.closed)


if __name__ == "__main__":
    unittest.main()
