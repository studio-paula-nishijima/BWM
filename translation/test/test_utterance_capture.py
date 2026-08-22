import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.audio.ring_buffer import AudioRingBuffer
from src.audio.utterance_capture import CapturePolicy, CompletedCapture, UtteranceCaptureController
from src.analysis.evaluate_utterance_capture import _capture_rows_and_utterances, match_captures, utterance_envelopes


class CaptureControllerTests(unittest.TestCase):
    def setUp(self):
        self.ring = AudioRingBuffer(100, 4.0)
        self.controller = UtteranceCaptureController(100, self.ring, CapturePolicy(0.3, 0.2, 0.1, 1.2), "x.wav", "temporal_v2_context")

    def feed(self, index, trigger=False, candidate=True):
        frame = np.full(10, index, dtype=np.float32)
        self.ring.append(frame)
        return self.controller.process_frame(frame, index, trigger, candidate)

    def test_real_trigger_starts_once_with_pre_roll_and_endpoint_post_roll(self):
        self.feed(0); self.feed(1); self.feed(2)
        self.assertIsNone(self.feed(3, trigger=True, candidate=True))
        self.assertTrue(self.controller.is_capturing)
        self.feed(4, candidate=False)  # short negative gap
        self.assertTrue(self.controller.is_capturing)
        self.feed(5, candidate=True)   # recovery resets negative evidence
        self.feed(6, candidate=False)
        self.feed(7, candidate=False)  # logical endpoint after sustained negative run
        capture = self.feed(8, candidate=False)
        self.assertEqual(capture.completion_reason, "endpoint")
        self.assertEqual(capture.logical_end_frame, 7)
        self.assertEqual(capture.final_end_frame, 8)
        self.assertEqual(capture.pre_roll_available_seconds, 0.3)
        np.testing.assert_array_equal(capture.samples[:10], np.full(10, 1, dtype=np.float32))
        self.assertEqual(capture.samples[-1], 8)

    def test_no_capture_for_non_trigger_and_active_trigger_is_ignored(self):
        self.feed(0, candidate=False)
        self.assertFalse(self.controller.is_capturing)
        self.feed(1, trigger=True)
        self.feed(2, trigger=True)
        self.assertEqual(self.controller.ignored_trigger_count, 1)
        capture = self.controller.finish()
        self.assertEqual(capture.ignored_trigger_count, 1)
        self.assertEqual(len(self.controller.completed), 1)

    def test_beginning_of_stream_and_hard_maximum(self):
        small = UtteranceCaptureController(100, self.ring, CapturePolicy(4.0, 5.0, 0.5, 0.3))
        frame = np.zeros(10, dtype=np.float32); self.ring.append(frame)
        small.process_frame(frame, 0, emitted_trigger=True, temporal_candidate=True)
        for index in (1, 2):
            self.ring.append(frame)
            result = small.process_frame(frame, index, temporal_candidate=True)
        self.assertEqual(result.completion_reason, "max_duration")
        self.assertEqual(result.pre_roll_available_seconds, 0.1)


class CaptureEvaluationTests(unittest.TestCase):
    def capture(self, start, end, index=0):
        return CompletedCapture(np.zeros(int((end-start)*100), dtype=np.float32), 100, "x.wav", "temporal_v2_context", index,
            0, int((start + .1)*100), 0, int(start*100), None, None, 0, int(end*100), "endpoint", 4, 1, 1.5, .5, 12)

    def test_legacy_whisper_rows_become_envelopes_and_coverage_is_explicit(self):
        annotations = pd.DataFrame([{"wav_file":"x.wav", "start_seconds":1., "end_seconds":2., "label":"whisper", "utterance_id":pd.NA,
            "language":"en", "transcription":"hello", "speaker_id":"s", "session_id":"a"}])
        utterances = utterance_envelopes(annotations)
        captures = [self.capture(.5, 2.5)]
        cap_rows, utt_rows = _capture_rows_and_utterances(captures, utterances, "temporal_v2_context")
        self.assertTrue(cap_rows.complete_envelope_covered.iloc[0])
        self.assertEqual(cap_rows.extra_audio_before_seconds.iloc[0], .5)
        self.assertEqual(cap_rows.extra_audio_after_seconds.iloc[0], .5)
        self.assertTrue(utt_rows.complete_envelope_covered.iloc[0])

    def test_merge_split_and_false_capture_are_visible(self):
        utterances = pd.DataFrame([
            {"wav_file":"x.wav", "utterance_id":"a", "effective_utterance_id":"a", "ground_truth_start":1., "ground_truth_end":2., "language":"", "transcription":"", "speaker_id":"", "session_id":""},
            {"wav_file":"x.wav", "utterance_id":"b", "effective_utterance_id":"b", "ground_truth_start":2.1, "ground_truth_end":3., "language":"", "transcription":"", "speaker_id":"", "session_id":""},
        ])
        merged, false = self.capture(.5, 3.5, 0), self.capture(5., 6., 1)
        matches, _ = match_captures([merged, false], utterances)
        self.assertEqual(matches[0]["overlap_count"], 2)
        self.assertIsNone(matches[1]["matched"])


if __name__ == "__main__":
    unittest.main()
