"""
Detector interfaces and factories.

Stage 3D:
Separates speech detection and whisper detection
while allowing interchangeable implementations.
"""



from .models import (
    WhisperDetectionResult,
    SpeechDetectionResult
)
from .detectors.whisper_feature import FeatureWhisperDetector
from .detectors.speech_feature import FeatureSpeechDetector





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
    implementation="feature",
    **kwargs
):
    """
    Create speech detector implementation.

    Future examples:

        feature
        silero
        webrtc
    """

    if implementation == "feature":

        return FeatureSpeechDetector(
            **kwargs
        )

    raise ValueError(
        f"Unknown speech detector: {implementation}"
    )
