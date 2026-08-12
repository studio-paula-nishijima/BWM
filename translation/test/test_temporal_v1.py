import sys
import types
import csv
import tempfile
import unittest
from pathlib import Path
import yaml

import numpy as np

# This test replaces feature extraction deterministically.  Provide the tiny
# import surface needed by AudioFeatures on developer machines without SciPy.
if "scipy.signal" not in sys.modules:
    scipy = types.ModuleType("scipy")
    signal = types.ModuleType("scipy.signal")
    signal.butter = lambda *args, **kwargs: (None, None)
    signal.lfilter = lambda _b, _a, samples: samples
    scipy.signal = signal
    sys.modules["scipy"] = scipy
    sys.modules["scipy.signal"] = signal

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from whisper.detectors.whisper_temporal_v1 import TemporalV1WhisperDetector
from whisper.features import AudioFeatures
from whisper.models import SpeechDetectionResult
from whisper.pipeline import DetectorPipeline
from app_logging.csv_logger import WhisperCSVLogger


def values(low):
    return {"rms": 0.0, "zcr": 0.1, "entropy": 1.0, "centroid": 1000.0,
            "band_low": low, "band_mid": 1.0 - low, "band_high": 0.0,
            "ratio_low": low, "ratio_mid": 1.0 - low, "ratio_high": 0.0,
            "total_band_energy": 1.0, "low_proportion": low, "mid_proportion": 1.0-low, "high_proportion": 0.0,
            "low_proportion_std": None, "mid_proportion_std": None, "high_proportion_std": None,
            "zcr_std": None, "entropy_std": None, "centroid_std": None, "spectral_flux": None,
            "voicing": 0.0, "hnr": 0.0, "cepstral_peak_prominence": 0.0, "spectral_slope": 0.0,
            "spectral_rolloff": 0.0, "spectral_flatness": 0.0}


class TemporalV1Tests(unittest.TestCase):
    frame = np.zeros(480, dtype=np.float32)

    def detector(self, sequence, **kwargs):
        d = TemporalV1WhisperDetector(rolling_window_frames=3, **kwargs)
        iterator = iter(sequence)
        def extract(_, **_kwargs):
            result = values(next(iterator))
            # Match the detector's rolling statistic without relying on FFTs.
            history = getattr(extract, "history", []) + [result["low_proportion"]]
            extract.history = history[-3:]
            if len(extract.history) == 3:
                result["low_proportion_std"] = float(np.std(extract.history))
            return result
        d.features.extract = extract
        return d

    def classify(self, detector, probability):
        return detector.classify(self.frame, SpeechDetectionResult(speech_probability=probability))

    def test_requires_full_window_then_all_conditions_pass(self):
        d = self.detector([0.0, 0.2, 0.0])
        self.assertFalse(self.classify(d, .1).is_whisper)
        self.assertFalse(self.classify(d, .1).is_whisper)
        result = self.classify(d, .1)
        self.assertTrue(result.temporal_v1_window_full)
        self.assertTrue(result.temporal_v1_raw_is_whisper)
        self.assertEqual(result.temporal_v1_qualifying_run, 1)
        self.assertEqual(result.confirmation_frames, 20)

    def test_silero_bounds_and_state_are_isolated(self):
        for probability in (.004, .51):
            d = self.detector([0.0, 0.2, 0.0])
            for _ in range(3): result = self.classify(d, probability)
            self.assertFalse(result.temporal_v1_raw_is_whisper)
        first, second = self.detector([0.0, .2, 0.0]), self.detector([0.0, .2, 0.0])
        self.classify(first, .1)
        self.assertFalse(self.classify(second, .1).temporal_v1_window_full)

    def test_profile_lower_bound_accepts_0_0025_and_uses_population_std(self):
        d = self.detector([0.0, 0.2, 0.0], silero_median_min=.0025)
        for _ in range(3): result = self.classify(d, .0025)
        self.assertTrue(result.temporal_v1_raw_is_whisper)
        self.assertAlmostEqual(result.temporal_v1_low_proportion_std, np.std([0.0, 0.2, 0.0], ddof=0))

    def test_current_frame_low_proportion_max_is_inclusive_and_resets_run(self):
        for low, expected in ((.84, True), (.85, True), (.86, False)):
            d = self.detector([0.0, .2, low], low_proportion_max=.85)
            for _ in range(3): result = self.classify(d, .1)
            self.assertEqual(result.temporal_v1_low_proportion_max_pass, expected)
            self.assertEqual(result.temporal_v1_raw_is_whisper, expected)
            self.assertEqual(result.temporal_v1_qualifying_run, int(expected))

    def test_low_proportion_max_can_be_disabled_and_is_validated(self):
        d = self.detector([0.0, .2, .99], low_proportion_max=None)
        for _ in range(3): result = self.classify(d, .1)
        self.assertTrue(result.temporal_v1_raw_is_whisper)
        self.assertTrue(result.temporal_v1_low_proportion_max_pass)
        self.assertIsNone(result.temporal_v1_low_proportion_max)
        for threshold in (-.01, 1.01):
            with self.assertRaises(ValueError):
                TemporalV1WhisperDetector(low_proportion_max=threshold)

    def test_all_current_profiles_configure_the_same_low_proportion_maximum(self):
        with (Path(__file__).resolve().parents[1] / "configs" / "whisper.yaml").open() as handle:
            config = yaml.safe_load(handle)
        for profile in ("webrtc_assisted_temporal", "temporal_only", "analysis_full"):
            self.assertEqual(config["detector_profiles"][profile]["low_proportion_max"], .85)

    def test_reset_and_pipeline_use_one_speech_result_per_frame(self):
        d = self.detector([0.0, .2, 0.0, 0.0, .2, 0.0])
        class Speech:
            calls = 0
            def classify(self, _frame):
                self.calls += 1
                return SpeechDetectionResult(speech_probability=.1)
        speech = Speech()
        pipeline = DetectorPipeline(d, mode="shadow", speech_detector=speech)
        for _ in range(3): result = pipeline.process(self.frame)
        self.assertEqual(speech.calls, 3)
        self.assertTrue(result.whisper.temporal_v1_raw_is_whisper)
        self.assertTrue(d._qualifying_run)
        pipeline.reset()
        self.assertEqual(d._qualifying_run, 0)
        self.assertEqual(len(d._silero_history), 0)

    def test_feature_observability_uses_blank_first_flux_and_full_rolling_window(self):
        features = AudioFeatures(rolling_window_frames=3)
        features.bandpass = lambda frame: frame
        first = features.extract(np.sin(2 * np.pi * 500 * np.arange(480) / 16000).astype(np.float32))
        second = features.extract(np.sin(np.linspace(0, 10, 480)).astype(np.float32))
        third = features.extract(np.zeros(480, dtype=np.float32))
        self.assertIsNone(first["spectral_flux"])
        self.assertIsNotNone(second["spectral_flux"])
        self.assertIsNone(second["low_proportion_std"])
        self.assertIsNotNone(third["low_proportion_std"])
        self.assertAlmostEqual(first["low_proportion"] + first["mid_proportion"] + first["high_proportion"], 1.0)

    def test_csv_keeps_temporal_values_in_named_columns(self):
        d = self.detector([0.0, .2, .85], low_proportion_max=.85)
        for _ in range(3): result = self.classify(d, .1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "temporal.csv"
            logger = WhisperCSVLogger(path)
            logger.log(0, result, False)
            logger.close()
            with path.open(newline="") as handle:
                row = next(csv.DictReader(handle))
        self.assertEqual(row["temporal_v1_raw_is_whisper"], "True")
        self.assertIn("temporal_v1_low_proportion_max", row)
        self.assertIn("temporal_v1_low_proportion_max_pass", row)
        self.assertEqual(row["temporal_v1_low_proportion_max"], "0.85")
        self.assertEqual(row["temporal_v1_low_proportion_max_pass"], "True")
        self.assertNotIn("confirmation_frames", row)


if __name__ == "__main__":
    unittest.main()
