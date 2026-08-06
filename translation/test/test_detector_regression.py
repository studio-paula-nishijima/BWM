"""Regression tests for detector factory and existing non-Silero behaviour."""

import sys
import unittest
from pathlib import Path

import numpy as np


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from whisper.detector import create_speech_detector
from whisper.detectors.speech_feature import FeatureSpeechDetector


class FixedFeatureExtractor:
    def extract(self, _frame):
        return {
            "rms": 0.01,
            "zcr": 0.1,
            "entropy": 4.0,
            "centroid": 1000.0,
        }


class RecordingSileroModel:
    def __init__(self):
        self.reset_calls = 0

    def __call__(self, _samples, _sample_rate):
        return 0.75

    def reset_states(self):
        self.reset_calls += 1


class DetectorRegressionTests(unittest.TestCase):
    def test_feature_backend_keeps_its_existing_score_contract(self):
        detector = FeatureSpeechDetector()
        detector.features = FixedFeatureExtractor()

        result = detector.classify(np.zeros(480, dtype=np.float32))

        self.assertTrue(result.is_speech)
        self.assertEqual(result.speech_probability, 1.0)

    def test_factory_creates_the_injected_silero_backend_once(self):
        backend = RecordingSileroModel()
        detector = create_speech_detector("silero", model=backend)

        self.assertIs(detector.model, backend)
        self.assertEqual(backend.reset_calls, 1)


if __name__ == "__main__":
    unittest.main()
