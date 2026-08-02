"""
Detector interfaces and factories.

Stage 3D:
Separates speech detection and whisper detection
while allowing interchangeable implementations.
"""

from abc import ABC, abstractmethod

from .models import (
    WhisperDetectionResult,
    SpeechDetectionResult
)
from .detectors.whisper_feature import FeatureWhisperDetector
from .detectors.speech_custom import CustomSpeechDetector



# ============================================================
# Base interfaces
# ============================================================


class WhisperDetector(ABC):
    """
    Interface for whisper classifiers.

    Every whisper implementation must provide:

        classify(frame) -> DetectionResult
    """

    @abstractmethod
    def classify(self, frame):
        pass



class SpeechDetector(ABC):
    """
    Interface for speech presence classifiers.

    Every speech implementation must provide:

        classify(frame) -> SpeechDetectionResult
    """

    @abstractmethod
    def classify(self, frame):
        pass



# ============================================================
# Factories
# ============================================================


def create_whisper_detector(
    implementation="feature",
    **kwargs
):
    """
    Create whisper detector implementation.

    Future examples:

        feature
        cnn
        transformer
    """

    if implementation == "feature":

        return FeatureWhisperDetector(
            **kwargs
        )


    raise ValueError(
        f"Unknown whisper detector: {implementation}"
    )



def create_speech_detector(
    implementation="custom",
    **kwargs
):
    """
    Create speech detector implementation.

    Future examples:

        custom
        silero
        webrtc
    """

    if implementation == "custom":

        return CustomSpeechDetector(
            **kwargs
        )


    raise ValueError(
        f"Unknown speech detector: {implementation}"
    )
