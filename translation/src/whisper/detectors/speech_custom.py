from ..models import SpeechDetectionResult


class CustomSpeechDetector:
    """
    Placeholder speech detector for Stage 3D.

    Current behaviour:
    Always returns speech=True.

    This preserves the existing single-stage whisper detector
    behaviour while creating the new speech detector interface.
    """

    def __init__(self, **kwargs):
        pass


    def classify(self, frame):

        return SpeechDetectionResult(

            is_speech=True,

            speech_probability=1.0,

            features={}

        )
