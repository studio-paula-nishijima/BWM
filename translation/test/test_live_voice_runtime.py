import sys
import time
import unittest
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audio.ring_buffer import AudioRingBuffer
from audio.utterance_capture import CapturePolicy, UtteranceCaptureController
from analysis.asr_evaluation import ASRResult
from live.asr_worker import ASRWorkerConfig, PersistentASRWorker
from live.voice_runtime import LiveASRCoordinator, VoiceLifecycle, VoiceState
from live.asr_result_log import ASRResultLogger


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
            self.assertTrue(any("[ASR] complete:" in item for item in events))
            self.assertEqual(runtime.lifecycle.state, VoiceState.CAPTURE_PROCESSING)
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

    def test_quiescent_policy_blocks_new_trigger_without_waking_worker(self):
        runtime, events = self.make()
        runtime._interaction_admission = lambda: False
        try:
            self.feed(runtime)
            self.assertEqual(runtime.capture.completed, [])
            self.assertTrue(any("capture ignored: quiescent" in item for item in events))
        finally:
            runtime.shutdown()

    def test_trigger_source_is_observable_without_changing_capture_path(self):
        runtime, events = self.make()
        try:
            frame = np.zeros(10, np.float32); runtime.capture.ring_buffer.append(frame)
            runtime.process_frame(frame, 0, emitted_trigger=True, temporal_candidate=False, trigger_source="button")
            self.assertTrue(any("source=button" in item for item in events))
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

    def test_busy_interaction_does_not_admit_second_capture_until_released(self):
        runtime, events = self.make()
        try:
            self.feed(runtime)
            self.assertEqual(runtime.lifecycle.state, VoiceState.CAPTURE_PROCESSING)
            self.feed(runtime, start=8, count=2, trigger_at=8)
            self.assertEqual(len(runtime.capture.completed), 1)
            self.assertTrue(any("[WhisperInteraction] capture ignored: busy (capture_processing)" in item for item in events))
            self.assertTrue(runtime.complete_interaction("test release"))
            self.feed(runtime, start=10, count=8, trigger_at=10)
            self.assertEqual(len(runtime.capture.completed), 2)
        finally:
            runtime.shutdown()

    def test_worker_unavailability_and_empty_text_are_visible(self):
        events = []
        ring = AudioRingBuffer(100, 1)
        capture = UtteranceCaptureController(100, ring, CapturePolicy(0, None, 0, .1), "live", "p")
        runtime = LiveASRCoordinator(capture, PersistentASRWorker(ASRWorkerConfig(worker_nice=0), backend_factory=fake_factory), emit=events.append)
        runtime.lifecycle.set(VoiceState.LISTENING)
        frame = np.zeros(10, np.float32); ring.append(frame)
        runtime.process_frame(frame, 0, emitted_trigger=True, temporal_candidate=False)
        ring.append(frame)
        runtime.process_frame(frame, 1, emitted_trigger=False, temporal_candidate=False)
        self.assertIn("[ASR] busy: worker_unavailable (live:0)", events)

    def test_exhibition_releases_after_asr_without_response_displayed(self):
        runtime, _ = self.make()
        runtime.release_on_asr_result = True
        try:
            self.feed(runtime)
            for _ in range(100):
                runtime.poll()
                if runtime.lifecycle.state is VoiceState.LISTENING: break
                time.sleep(.02)
            self.assertEqual(runtime.lifecycle.state, VoiceState.LISTENING)
            self.assertNotIn(VoiceState.RESPONSE_DISPLAYED, [runtime.lifecycle.state])
        finally:
            runtime.shutdown()

    def test_only_nonempty_successful_transcripts_are_logged_as_safe_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcripts.csv"
            logger = ASRResultLogger(path, emit=lambda _: None)
            logger({"capture_id": "live:3", "detector_profile": "p", "status": "ok",
                    "inference_duration": .25,
                    "result": {"recognized_text": 'water, "river"\nand mist', "detected_language": "en"}})
            logger({"capture_id": "live:4", "detector_profile": "p", "status": "timeout",
                    "inference_duration": 10, "error": "inference timeout", "result": {}})
            logger({"capture_id": "live:5", "status": "error", "error": "worker failed",
                    "result": {"recognized_text": "water"}})
            logger({"capture_id": "live:6", "status": "ok", "result": {"recognized_text": "  "}})
            logger({"capture_id": "live:7", "status": "ok", "result": {"recognized_text": "second", "detected_language": "de"}})
            import csv
            with path.open(encoding="utf-8", newline="") as stream:
                records = list(csv.reader(stream))
            self.assertEqual(records[0], ["timestamp", "capture_id", "language", "text"])
            self.assertEqual(records[1][1:], ["live:3", "en", 'water, "river"\nand mist'])
            self.assertEqual(records[2][1:], ["live:7", "de", "second"])
            self.assertEqual(len(records), 3)


if __name__ == "__main__":
    unittest.main()
