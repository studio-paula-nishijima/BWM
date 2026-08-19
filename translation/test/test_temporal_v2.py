import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from whisper.detectors.whisper_temporal_v2 import TemporalV2WhisperDetector
from whisper.models import SpeechDetectionResult, WhisperDetectionResult
from whisper.profiles import TemporalProfilePolicy


class TemporalV2Tests(unittest.TestCase):
    def detector(self, **settings):
        detector = TemporalV2WhisperDetector(rolling_window_frames=10, **settings)
        detector.features.extract = lambda frame, analysis_full=False: frame
        return detector

    @staticmethod
    def features(low=.85, low_std=.05, zcr_std=.020):
        return {"zcr": .1, "band_low": 0., "band_mid": 0., "band_high": 0., "total_band_energy": 1., "low_proportion": low, "mid_proportion": 0., "high_proportion": 0., "low_proportion_std": low_std, "zcr_std": zcr_std}

    def test_boundaries_and_window_readiness(self):
        detector = self.detector()
        for _ in range(9): self.assertFalse(detector.classify(self.features(), SpeechDetectionResult(speech_probability=.0003)).temporal_v2_raw_is_whisper)
        self.assertTrue(detector.classify(self.features(), SpeechDetectionResult(speech_probability=.0003)).temporal_v2_raw_is_whisper)
        for key, value in (("low", .85001), ("low_std", .049), ("zcr_std", .019)):
            detector = self.detector()
            for _ in range(9): detector.classify(self.features(), SpeechDetectionResult(speech_probability=.1))
            kwargs = {key: value}
            self.assertFalse(detector.classify(self.features(**kwargs), SpeechDetectionResult(speech_probability=.1)).temporal_v2_raw_is_whisper)

    def test_context_exactly_five_and_recall_disabled(self):
        context = self.detector(context_enabled=True, context_window_frames=50, context_silero_threshold=.1, context_min_frames=5)
        recall = self.detector(context_enabled=False)
        for index in range(10):
            probability = .1 if index < 5 else .01
            a = context.classify(self.features(), SpeechDetectionResult(speech_probability=probability))
            b = recall.classify(self.features(), SpeechDetectionResult(speech_probability=probability))
        self.assertTrue(a.temporal_v2_context_active)
        self.assertEqual(a.temporal_v2_context_high_silero_count, 5)
        self.assertIsNone(b.temporal_v2_context_active)
        self.assertEqual(a.temporal_v2_raw_is_whisper, b.temporal_v2_raw_is_whisper)

    def test_context_expires_and_zero_energy_is_safe(self):
        detector = self.detector(context_enabled=True, context_window_frames=5, context_silero_threshold=.1, context_min_frames=2)
        for probability in (.1, .1, .01, .01, .01, .01):
            result = detector.classify(self.features(low=0), SpeechDetectionResult(speech_probability=probability))
        self.assertFalse(result.temporal_v2_context_active)
        detector = self.detector()
        for _ in range(10): result = detector.classify(self.features(low=0), SpeechDetectionResult(speech_probability=.5))
        self.assertTrue(result.temporal_v2_raw_is_whisper)

    def test_failed_candidate_resets_run(self):
        detector = self.detector()
        for _ in range(10): result = detector.classify(self.features(), SpeechDetectionResult(speech_probability=.1))
        self.assertEqual(result.temporal_v2_qualifying_run, 1)
        self.assertEqual(detector.classify(self.features(low=.9), SpeechDetectionResult(speech_probability=.1)).temporal_v2_qualifying_run, 0)

    def test_policy_crossings_and_dynamic_requirement_drop(self):
        settings = {"webrtc_enter_frames": 1, "webrtc_exit_frames": 1, "assisted_confirmation_frames": 15, "fallback_confirmation_frames": 24, "context_confirmation_frames": 30}
        policy = TemporalProfilePolicy("temporal_v2_context", settings)
        result = WhisperDetectionResult(temporal_v2_raw_is_whisper=True, temporal_v2_qualifying_run=30, temporal_v2_context_active=True)
        self.assertTrue(policy.update(result, None).trigger)
        policy = TemporalProfilePolicy("temporal_v2_recall", settings)
        assisted = WhisperDetectionResult(temporal_v2_raw_is_whisper=True, temporal_v2_qualifying_run=15, temporal_v2_context_active=False)
        self.assertTrue(policy.update(assisted, type("Speech", (), {"is_speech": True})()).trigger)
        policy = TemporalProfilePolicy("temporal_v2_context", settings)
        result.temporal_v2_qualifying_run, result.temporal_v2_context_active = 24, False
        self.assertTrue(policy.update(result, None).trigger)
        self.assertEqual(policy.update(WhisperDetectionResult(temporal_v2_raw_is_whisper=False), None).trigger, False)


if __name__ == "__main__": unittest.main()
