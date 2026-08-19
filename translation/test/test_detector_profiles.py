import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from whisper.models import WhisperDetectionResult
from whisper.profiles import PROFILE_NAMES, TemporalProfilePolicy


def temporal(candidate, run):
    return WhisperDetectionResult(temporal_v1_raw_is_whisper=candidate, temporal_v1_qualifying_run=run)


ASSISTED = {"webrtc_enter_frames": 2, "webrtc_exit_frames": 2, "assisted_confirmation_frames": 3, "fallback_confirmation_frames": 5}
ONLY = {"fallback_confirmation_frames": 5}


class Speech:
    def __init__(self, speech): self.is_speech = speech


class DetectorProfileTests(unittest.TestCase):
    def test_profile_names_and_temporal_only_never_uses_webrtc(self):
        self.assertEqual(PROFILE_NAMES, ("webrtc_assisted_temporal", "temporal_only", "analysis_full", "temporal_v2_context", "temporal_v2_recall"))
        policy = TemporalProfilePolicy("temporal_only", ONLY)
        self.assertFalse(policy.update(temporal(True, 4), Speech(True)).trigger)
        decision = policy.update(temporal(True, 5), Speech(True))
        self.assertTrue(decision.trigger)
        self.assertEqual(decision.trigger_route, "temporal_fallback")

    def test_assist_debounce_and_one_trigger_per_run(self):
        policy = TemporalProfilePolicy("webrtc_assisted_temporal", ASSISTED)
        self.assertFalse(policy.update(temporal(True, 1), Speech(True)).webrtc_assist_open)
        self.assertTrue(policy.update(temporal(True, 2), Speech(True)).webrtc_assist_open)
        decision = policy.update(temporal(True, 3), Speech(False))
        self.assertTrue(decision.trigger)
        self.assertEqual(decision.trigger_route, "webrtc_assisted")
        self.assertEqual(decision.confirmation_requirement, 3)
        self.assertFalse(policy.update(temporal(True, 5), Speech(False)).trigger)

    def test_fallback_and_reset_permit_new_trigger(self):
        policy = TemporalProfilePolicy("webrtc_assisted_temporal", ASSISTED)
        self.assertTrue(policy.update(temporal(True, 5), Speech(False)).trigger)
        self.assertFalse(policy.update(temporal(False, 0), Speech(False)).trigger)
        self.assertTrue(policy.update(temporal(True, 5), Speech(False)).trigger)

    def test_assist_closes_after_consecutive_negatives(self):
        policy = TemporalProfilePolicy("webrtc_assisted_temporal", ASSISTED)
        policy.update(temporal(True, 1), Speech(True)); self.assertTrue(policy.update(temporal(True, 2), Speech(True)).webrtc_assist_open)
        self.assertTrue(policy.update(temporal(True, 3), Speech(False)).webrtc_assist_open)
        self.assertFalse(policy.update(temporal(True, 4), Speech(False)).webrtc_assist_open)

    def test_analysis_full_reconstructs_the_same_mode_zero_gate(self):
        policy = TemporalProfilePolicy("analysis_full", ASSISTED)
        self.assertFalse(policy.update(temporal(True, 1), Speech(True)).webrtc_assist_open)
        decision = policy.update(temporal(True, 2), Speech(True))
        self.assertTrue(decision.webrtc_assist_open)
        self.assertEqual(decision.confirmation_requirement, 3)
        decision = policy.update(temporal(True, 3), Speech(True))
        self.assertTrue(decision.trigger)
        self.assertEqual(decision.trigger_route, "webrtc_assisted")


if __name__ == "__main__":
    unittest.main()
