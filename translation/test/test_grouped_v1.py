import sys
import unittest
from pathlib import Path

import numpy as np

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from whisper.detectors.whisper_grouped_v1 import GroupedV1WhisperDetector
from whisper.models import SpeechDetectionResult
from whisper.pipeline import DetectorPipeline


class GroupedV1Tests(unittest.TestCase):
    frame = np.ones(480, dtype=np.float32)

    def detector(self):
        result = GroupedV1WhisperDetector()
        result.features.extract = lambda _frame: {
            "rms": .01, "zcr": .081, "entropy": 2.61, "centroid": 1000.,
            "band_low": 1., "band_mid": 1., "band_high": 1.,
            "ratio_low": 1 / 3, "ratio_mid": 1 / 3, "ratio_high": 1 / 3,
        }
        return result

    def classify(self, detector, probability):
        return detector.classify(self.frame, SpeechDetectionResult(speech_probability=probability))

    def test_candidate_enters_at_three_and_exits_at_ten(self):
        detector = self.detector()
        self.assertFalse(self.classify(detector, .005).stage1_candidate)
        self.assertFalse(self.classify(detector, .005).stage1_candidate)
        self.assertTrue(self.classify(detector, .005).stage1_candidate)
        for _ in range(9):
            self.assertTrue(self.classify(detector, 0).stage1_candidate)
        self.assertFalse(self.classify(detector, 0).stage1_candidate)

    def test_interrupted_candidate_run_resets_counter(self):
        detector = self.detector()
        self.classify(detector, .01); self.classify(detector, .01)
        self.assertEqual(self.classify(detector, 0).stage1_enter_count, 0)
        self.assertFalse(self.classify(detector, .01).stage1_candidate)

    def test_group_a_is_one_group_and_low_ratio_uses_safe_denominator(self):
        detector = self.detector()
        detector.features.extract = lambda _frame: {
            "rms": 0., "zcr": .081, "entropy": 2.59, "centroid": 1280.,
            "band_low": 0., "band_mid": 0., "band_high": 0., "ratio_low": 0., "ratio_mid": 0., "ratio_high": 0.,
        }
        result = self.classify(detector, 0)
        self.assertTrue(result.group_a_pass)
        self.assertEqual(result.group_count, 2)
        self.assertEqual(result.low_proportion, 0.0)
        self.assertTrue(result.group_c_pass)

    def test_high_silero_penalty_needs_full_window_and_three_runs(self):
        detector = self.detector()
        for _ in range(12):
            result = self.classify(detector, .9)
        self.assertTrue(result.high_silero_normal_evidence)
        self.assertEqual(result.silero_penalty, 1)
        self.assertEqual(result.effective_group_score, 2)

    def test_raw_is_visible_when_candidate_is_false_and_reset_clears_state(self):
        detector = self.detector()
        result = self.classify(detector, 0)
        self.assertTrue(result.grouped_v1_raw_is_whisper)
        self.assertFalse(result.stage2_is_whisper)
        detector.reset()
        self.assertEqual(detector._high_silero_count, 0)

    def test_direct_mode_rejects_grouped_v1(self):
        with self.assertRaisesRegex(ValueError, "cannot run in direct"):
            DetectorPipeline(self.detector(), mode="direct")


if __name__ == "__main__":
    unittest.main()
