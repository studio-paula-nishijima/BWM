import sys
import types
import unittest
import csv
import tempfile
from pathlib import Path

import numpy as np

# The project runtime supplies SciPy; these deterministic backend tests do not
# use it, so keep them runnable in the lightweight desktop test runtime.
if "scipy.signal" not in sys.modules:
    scipy = types.ModuleType("scipy"); signal = types.ModuleType("scipy.signal")
    signal.butter = lambda *a, **k: (None, None); signal.lfilter = lambda _b, _a, samples: samples
    scipy.signal = signal; sys.modules["scipy"] = scipy; sys.modules["scipy.signal"] = signal

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from whisper.detector import create_speech_detector
from whisper.detectors.speech_webrtc import WebRTCSpeechDetector
from whisper.models import SpeechDetectionResult, WhisperDetectionResult
from whisper.pipeline import DetectorPipeline
from app_logging.csv_logger import WhisperCSVLogger


class RecordingVad:
    def __init__(self, result=True): self.result, self.calls = result, []
    def is_speech(self, pcm, sample_rate): self.calls.append((pcm, sample_rate)); return self.result


class Speech:
    def __init__(self, value): self.value, self.calls = value, 0
    def classify(self, _): self.calls += 1; return SpeechDetectionResult(is_speech=self.value, speech_probability=.2)


class Whisper:
    def classify(self, _): return WhisperDetectionResult(is_whisper=True)


class WebRTCVadTests(unittest.TestCase):
    frame = np.array([-2., -.5, 0., .5, 2.] + [0.] * 475, dtype=np.float32)

    def test_factory_conversion_and_boolean_result(self):
        vad = RecordingVad()
        detector = create_speech_detector("webrtc", vad=vad, aggressiveness=1)
        result = detector.classify(self.frame)
        self.assertTrue(result.is_speech)
        self.assertIsNone(result.speech_probability)
        pcm, rate = vad.calls[0]
        self.assertEqual(rate, 16000)
        self.assertEqual(np.frombuffer(pcm, dtype="<i2")[:5].tolist(), [-32767, -16384, 0, 16384, 32767])

    def test_validates_mode_and_frame_shape(self):
        with self.assertRaisesRegex(ValueError, "0, 1, 2, or 3"):
            WebRTCSpeechDetector(aggressiveness=4, vad=RecordingVad())
        with self.assertRaisesRegex(ValueError, "480 samples"):
            WebRTCSpeechDetector(vad=RecordingVad()).classify(np.zeros(479, dtype=np.float32))

    def test_comparison_is_observational(self):
        primary, comparison, whisper = Speech(False), Speech(True), Whisper()
        result = DetectorPipeline(whisper, primary, mode="speech_gate", comparison_speech_detector=comparison).process(np.zeros(480, dtype=np.float32))
        self.assertFalse(result.speech_gate_open)
        self.assertFalse(result.whisper_processed)
        self.assertTrue(result.speech_comparison.is_speech)
        self.assertEqual(primary.calls, 1)
        self.assertEqual(comparison.calls, 1)

    def test_multiple_comparison_modes_share_the_frame_without_gating_authority(self):
        primary, whisper = Speech(False), Whisper()
        mode_zero, mode_two = Speech(True), Speech(True)
        pipeline = DetectorPipeline(
            whisper, primary, mode="speech_gate",
            comparison_speech_detectors={0: mode_zero, 2: mode_two},
        )
        result = pipeline.process(np.zeros(480, dtype=np.float32))
        self.assertFalse(result.speech_gate_open)
        self.assertEqual(set(result.speech_comparisons), {0, 2})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.csv"
            logger = WhisperCSVLogger(path, comparison_speech_modes=(0, 2))
            logger.log(0, result, False); logger.close()
            with path.open(newline="") as handle: row = next(csv.DictReader(handle))
        self.assertEqual(row["webrtc_mode_0_is_speech"], "True")
        self.assertEqual(row["webrtc_mode_2_is_speech"], "True")

    def test_temporal_evidence_rejects_non_silero_primary(self):
        temporal = types.SimpleNamespace(requires_speech_evidence=True)
        with self.assertRaisesRegex(ValueError, "primary Silero"):
            DetectorPipeline(temporal, WebRTCSpeechDetector(vad=RecordingVad()), mode="shadow")


if __name__ == "__main__":
    unittest.main()
