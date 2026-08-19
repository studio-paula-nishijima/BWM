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
from .detectors.whisper_grouped_v1 import GroupedV1WhisperDetector
from .detectors.whisper_temporal_v1 import TemporalV1WhisperDetector
from .detectors.whisper_temporal_v2 import TemporalV2WhisperDetector
from .detectors.speech_feature import FeatureSpeechDetector
from .detectors.speech_silero import SileroSpeechDetector
from .detectors.speech_webrtc import WebRTCSpeechDetector





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

    if implementation in ("feature", "legacy"):
        allowed = {
            key: value for key, value in kwargs.items()
            if key in {"sample_rate", "rms_min", "rms_max", "zcr_min", "zcr_max",
                       "entropy_min", "decision_window", "trigger_ratio"}
        }
        return FeatureWhisperDetector(
            **allowed
        )
    if implementation == "grouped_v1":
        return GroupedV1WhisperDetector(**kwargs)
    if implementation == "temporal_v1":
        return TemporalV1WhisperDetector(**kwargs)
    if implementation == "temporal_v2":
        return TemporalV2WhisperDetector(**kwargs)


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
    elif implementation == "silero":

        return SileroSpeechDetector(
            **kwargs
        )
    elif implementation == "webrtc":
        return WebRTCSpeechDetector(**kwargs)

    raise ValueError(
        f"Unknown speech detector: {implementation}"
    )
