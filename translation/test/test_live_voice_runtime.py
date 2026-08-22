import sys
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audio.ring_buffer import AudioRingBuffer
from audio.utterance_capture import CapturePolicy, UtteranceCaptureController
from analysis.asr_evaluation import ASRResult
from live.asr_worker import ASRWorkerConfig, PersistentASRWorker
from live.voice_runtime import LiveASRCoordinator, VoiceLifecycle, VoiceState


class FakeBackend:
    def transcribe(self, audio, **_):
        return ASRResult("a partial question", "de", .9)


def fake_factory(_):
    return FakeBackend()


class SlowBackend(FakeBackend):
    def transcribe(self, audio, **kwargs):
        time.sleep(.25)
        return super().transcribe(audio, **kwargs)


def slow_factory(_):
    return SlowBackend()


class VoiceRuntimeTests(unittest.TestCase):
    def make(self, factory=fake_factory):
        events = []
        ring = AudioRingBuffer(100, 5)
        capture = UtteranceCaptureController(100, ring, CapturePolicy(.2, None, 0, .5), "live", "temporal_v2_context")
        worker = PersistentASRWorker(ASRWorkerConfig(queue_size=1, worker_nice=0), backend_factory=factory)
        runtime = LiveASRCoordinator(capture, worker, emit=events.append, source_id="live", detector_profile="temporal_v2_context")
        runtime.start()
        for _ in range(250):
            if worker.ready: return runtime, events
            if worker.startup_error: self.fail(worker.startup_error)
            time.sleep(.02)
        self.fail("worker did not start")

    def feed(self, runtime, start=0, count=8, trigger_at=1):
        for index in range(start, start + count):
            frame = np.full(10, index, np.float32)
            runtime.capture.ring_buffer.append(frame)
            runtime.process_frame(frame, index, emitted_trigger=index == trigger_at, temporal_candidate=False)

    def test_emitted_trigger_captures_once_and_preserves_identity(self):
        runtime, events = self.make()
        try:
            self.feed(runtime)
            self.assertEqual(len(runtime.capture.completed), 1)
            for _ in range(100):
                if runtime.poll(): break
                time.sleep(.02)
            result = runtime.results[-1]
            self.assertEqual(result["capture_id"], "live:0")
            self.assertEqual(result["detector_profile"], "temporal_v2_context")
            self.assertEqual(result["result"]["recognized_text"], "a partial question")
            self.assertTrue(any("[Capture] started" in item for item in events))
        finally:
            runtime.shutdown()

    def test_non_emitted_trigger_creates_no_capture_or_job(self):
        runtime, _ = self.make()
        try:
            self.feed(runtime, trigger_at=-1)
            self.assertEqual(runtime.capture.completed, [])
            self.assertEqual(runtime.results, [])
        finally:
            runtime.shutdown()

    def test_slow_asr_does_not_block_next_detector_frames(self):
        runtime, _ = self.make(slow_factory)
        try:
            started = time.monotonic()
            self.feed(runtime, count=4)  # completes max-duration capture and submits slow ASR
            self.feed(runtime, start=4, count=10, trigger_at=-1)
            self.assertLess(time.monotonic() - started, .15)
        finally:
            runtime.shutdown()

    def test_voice_lifecycle_uses_exact_names_and_deduplicates(self):
        events = []
        lifecycle = VoiceLifecycle(events.append)
        self.assertFalse(lifecycle.set("idle"))
        self.assertTrue(lifecycle.set("listening"))
        self.assertFalse(lifecycle.set("listening"))
        self.assertEqual(VoiceState.RESPONSE_DISPLAYED.value, "response_displayed")
        self.assertEqual(len(events), 1)

    def test_worker_unavailability_and_empty_text_are_visible(self):
        events = []
        ring = AudioRingBuffer(100, 1)
        capture = UtteranceCaptureController(100, ring, CapturePolicy(0, None, 0, .1), "live", "p")
        runtime = LiveASRCoordinator(capture, PersistentASRWorker(ASRWorkerConfig(worker_nice=0), backend_factory=fake_factory), emit=events.append)
        frame = np.zeros(10, np.float32); ring.append(frame)
        runtime.process_frame(frame, 0, emitted_trigger=True, temporal_candidate=False)
        ring.append(frame)
        runtime.process_frame(frame, 1, emitted_trigger=False, temporal_candidate=False)
        self.assertIn("[ASR] busy: worker_unavailable (live:0)", events)


if __name__ == "__main__":
    unittest.main()
