"""Focused regression tests for the Silero 480-to-512 streaming adapter."""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from whisper.detectors.speech_silero import SileroSpeechDetector
from whisper.models import SpeechDetectionResult, WhisperDetectionResult
from whisper.pipeline import DetectorPipeline


class RecordingSileroModel:
    """Small injected backend which makes window and reset calls observable."""

    def __init__(self):
        self.windows = []
        self.reset_calls = 0

    def __call__(self, samples, sample_rate):
        self.windows.append((np.array(samples, copy=True), sample_rate))
        return 0.75

    def reset_states(self):
        self.reset_calls += 1


class SileroStreamingTests(unittest.TestCase):
    def setUp(self):
        self.model = RecordingSileroModel()
        self.detector = SileroSpeechDetector(model=self.model)

    def test_accepts_feature_detector_options_passed_by_the_shared_factory(self):
        detector = SileroSpeechDetector(
            model=self.model,
            rms_min=0.003,
            rms_max=0.20,
            zcr_min=0.02,
            zcr_max=0.40,
            entropy_min=3.0,
            centroid_min=300,
            centroid_max=4000,
        )

        self.assertIs(detector.model, self.model)

    def test_default_torch_hub_load_is_noninteractive_for_systemd(self):
        calls = []
        loaded_model = RecordingSileroModel()

        def load(**kwargs):
            calls.append(kwargs)
            return loaded_model, object()

        fake_torch = types.SimpleNamespace(
            set_num_threads=lambda _count: None,
            hub=types.SimpleNamespace(load=load),
        )
        with mock.patch.dict(sys.modules, {"torch": fake_torch}):
            detector = SileroSpeechDetector()

        self.assertIs(detector.model, loaded_model)
        self.assertEqual(calls, [{
            "repo_or_dir": "snakers4/silero-vad",
            "model": "silero_vad",
            "force_reload": False,
            "trust_repo": True,
        }])

    def test_480_sample_frames_form_continuous_512_sample_windows(self):
        frames = [
            np.arange(
                1000 + index * 480, 1000 + (index + 1) * 480, dtype=np.float32
            )
            for index in range(8)
        ]

        results = [self.detector.classify(frame) for frame in frames]
        source_samples = np.concatenate(frames)
        observed = np.concatenate([window for window, _ in self.model.windows])

        self.assertEqual(len(self.model.windows), len(source_samples) // 512)
        np.testing.assert_array_equal(observed, source_samples[:len(observed)])
        self.assertTrue(results[0].features["pending"])
        self.assertFalse(results[0].features["inference_ran"])
        self.assertEqual(results[-1].features["buffered_samples"], len(source_samples) % 512)
        for _, sample_rate in self.model.windows:
            self.assertEqual(sample_rate, 16000)

    def test_residuals_and_diagnostics_are_correct_over_many_frames(self):
        windows_before = 0
        for frame_number in range(25):
            result = self.detector.classify(
                np.full(480, frame_number, dtype=np.float32)
            )
            samples_seen = (frame_number + 1) * 480
            total_windows = samples_seen // 512

            self.assertEqual(result.features["buffered_samples"], samples_seen % 512)
            self.assertEqual(
                result.features["windows_processed"], total_windows - windows_before
            )
            self.assertEqual(
                result.features["inference_ran"], total_windows > windows_before
            )
            windows_before = total_windows

    def test_a_large_input_can_produce_multiple_windows(self):
        frame = np.arange(1600, dtype=np.float32)

        result = self.detector.classify(frame)

        self.assertEqual(result.features["windows_processed"], 3)
        self.assertEqual(result.features["buffered_samples"], 64)
        np.testing.assert_array_equal(
            np.concatenate([window for window, _ in self.model.windows]), frame[:1536]
        )

    def test_reset_clears_buffer_probability_and_backend_state(self):
        self.detector.classify(np.arange(480, dtype=np.float32))
        self.detector.classify(np.arange(480, 960, dtype=np.float32))
        resets_before = self.model.reset_calls

        self.detector.reset()
        result = self.detector.classify(np.arange(480, dtype=np.float32))

        self.assertEqual(self.model.reset_calls, resets_before + 1)
        self.assertIsNone(self.detector._latest_probability)
        self.assertEqual(len(self.detector._samples), 480)
        self.assertTrue(result.features["pending"])
        self.assertEqual(result.speech_probability, 0.0)
        self.assertFalse(result.is_speech)

    def test_pipeline_reuses_one_silero_detector_instance(self):
        pipeline = DetectorPipeline(
            whisper_detector=CountingWhisperDetector(),
            speech_detector=self.detector,
            mode="shadow",
        )

        for _ in range(4):
            pipeline.process(np.ones(480, dtype=np.float32))

        self.assertIs(pipeline.speech_detector, self.detector)
        self.assertEqual(len(self.model.windows), 3)

    def test_pipeline_reset_forwards_the_real_stream_boundary(self):
        pipeline = DetectorPipeline(
            whisper_detector=CountingWhisperDetector(),
            speech_detector=self.detector,
            mode="shadow",
        )
        pipeline.process(np.ones(480, dtype=np.float32))
        reset_calls_before = self.model.reset_calls

        pipeline.reset()
        result = self.detector.classify(np.ones(480, dtype=np.float32))

        self.assertEqual(self.model.reset_calls, reset_calls_before + 1)
        self.assertTrue(result.features["pending"])
        self.assertEqual(result.features["buffered_samples"], 480)

    def test_direct_shadow_and_speech_gate_routing_is_unchanged(self):
        frame = np.zeros(480, dtype=np.float32)

        direct_whisper = CountingWhisperDetector()
        DetectorPipeline(direct_whisper, mode="direct").process(frame)
        self.assertEqual(direct_whisper.calls, 1)

        shadow_whisper = CountingWhisperDetector()
        shadow_speech = FixedSpeechDetector(is_speech=False)
        DetectorPipeline(shadow_whisper, shadow_speech, mode="shadow").process(frame)
        self.assertEqual((shadow_speech.calls, shadow_whisper.calls), (1, 1))

        gate_whisper = CountingWhisperDetector()
        closed_gate = FixedSpeechDetector(is_speech=False)
        DetectorPipeline(gate_whisper, closed_gate, mode="speech_gate").process(frame)
        self.assertEqual((closed_gate.calls, gate_whisper.calls), (1, 0))

        open_gate = FixedSpeechDetector(is_speech=True)
        DetectorPipeline(gate_whisper, open_gate, mode="speech_gate").process(frame)
        self.assertEqual((open_gate.calls, gate_whisper.calls), (1, 1))


class CountingWhisperDetector:
    def __init__(self):
        self.calls = 0
    def classify(self, _frame):
        self.calls += 1
        return WhisperDetectionResult(is_whisper=True)


class FixedSpeechDetector:
    def __init__(self, is_speech):
        self.is_speech = is_speech
        self.calls = 0

    def classify(self, _frame):
        self.calls += 1
        return SpeechDetectionResult(is_speech=self.is_speech)

if __name__ == "__main__":
    unittest.main()
