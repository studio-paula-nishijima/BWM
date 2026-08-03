"""
Feature-based Speech Presence Detector.

Stage 3F

Purpose:
    Classify audio as speech vs non-speech.

This detector is intentionally independent from the
Whisper detector.

It answers:

    "Is this likely human speech?"

rather than:

    "Is this whispered?"
"""

from ..interfaces import SpeechDetector
from ..features import AudioFeatures
from ..models import SpeechDetectionResult


class FeatureSpeechDetector(SpeechDetector):

    def __init__(
        self,
        sample_rate=16000,
        rms_min=0.003,
        rms_max=0.20,
        zcr_min=0.02,
        zcr_max=0.40,
        entropy_min=3.0,
        centroid_min=300,
        centroid_max=4000,
    ):

        self.features = AudioFeatures(
            sample_rate=sample_rate
        )

        self.rms_min = rms_min
        self.rms_max = rms_max

        self.zcr_min = zcr_min
        self.zcr_max = zcr_max

        self.entropy_min = entropy_min

        self.centroid_min = centroid_min
        self.centroid_max = centroid_max


    def classify(self, frame):

        f = self.features.extract(frame)

        score = 0

        # -----------------------------
        # RMS
        # -----------------------------

        if self.rms_min <= f["rms"] <= self.rms_max:
            score += 1

        # -----------------------------
        # ZCR
        # -----------------------------

        if self.zcr_min <= f["zcr"] <= self.zcr_max:
            score += 1

        # -----------------------------
        # Entropy
        # -----------------------------

        if f["entropy"] >= self.entropy_min:
            score += 1

        # -----------------------------
        # Spectral centroid
        # -----------------------------

        if (
            self.centroid_min
            <= f["centroid"]
            <= self.centroid_max
        ):
            score += 1

        probability = score / 4.0

        return SpeechDetectionResult(

            is_speech=score >= 3,

            speech_probability=probability,

            features=f,

        )
