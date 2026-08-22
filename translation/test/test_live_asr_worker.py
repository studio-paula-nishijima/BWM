import os, sys, time, unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analysis.asr_evaluation import ASRResult, AudioSegment
from live.asr_worker import ASRWorkerConfig, PersistentASRWorker, _reset_worker_signal_handlers

class FakeBackend:
    loads = 0
    def __init__(self): type(self).loads += 1
    def transcribe(self, audio, **kwargs): return ASRResult("river question", "en")
def fake_factory(_config): return FakeBackend()
class SlowBackend(FakeBackend):
    def transcribe(self, audio, **kwargs):
        time.sleep(.5)
        return super().transcribe(audio, **kwargs)
def slow_factory(_config): return SlowBackend()

class LiveASRTests(unittest.TestCase):
    def audio(self): return AudioSegment(np.zeros(160, np.float32), 16000, "capture.wav")
    def worker(self, factory=fake_factory):
        worker = PersistentASRWorker(ASRWorkerConfig(queue_size=1, worker_nice=0), backend_factory=factory); worker.start()
        # Windows uses spawn; importing the test module can take longer than a
        # forked Pi worker, so permit a bounded five-second startup window.
        for _ in range(250):
            if worker.ready: return worker
            if worker.startup_error: self.fail(worker.startup_error)
            time.sleep(.02)
        self.fail("worker did not become ready")
    def test_reuses_process_and_returns_structured_result(self):
        worker = self.worker(slow_factory)
        try:
            job, status = worker.submit(self.audio(), {"capture_id": "a"}); self.assertEqual(status, "accepted")
            for _ in range(250):
                items = worker.poll()
                if items: break
                time.sleep(.02)
            self.assertEqual(items[0]["result"]["recognized_text"], "river question")
        finally: worker.shutdown()
    def test_queue_is_bounded_without_detector_dependency(self):
        worker = self.worker()
        try:
            first, status = worker.submit(self.audio(), {"capture_id": "a"})
            self.assertEqual(status, "accepted")
            # Let the already-ready worker take the active job; the bounded
            # queue then represents the single allowed pending request.
            time.sleep(.1)
            second, status = worker.submit(self.audio(), {"capture_id": "b"})
            self.assertEqual(status, "accepted")
            third, status = worker.submit(self.audio(), {"capture_id": "c"})
            self.assertIsNone(third); self.assertEqual(status, "queue_full")
        finally: worker.shutdown()
    def test_invalid_configuration_is_clear(self):
        with self.assertRaises(ValueError): ASRWorkerConfig(cpu_threads=0).validate()

    @unittest.skipUnless(os.name == "posix", "Signal inheritance applies to forked POSIX workers")
    def test_worker_resets_inherited_application_signal_handlers(self):
        with patch("live.asr_worker.signal.signal") as reset:
            _reset_worker_signal_handlers()
        self.assertEqual(reset.call_count, 2)

if __name__ == "__main__": unittest.main()
