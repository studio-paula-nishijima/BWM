"""
Detector processing pipeline.

Stage 3E:

Modes:

direct:
    Whisper detector only

speech_gate:
    Speech detector controls whisper execution

shadow:
    Speech detector runs and logs,
    but does not affect whisper decisions
"""


from dataclasses import dataclass

from .models import (
    WhisperDetectionResult,
    SpeechDetectionResult
)


@dataclass
class DetectorPipelineResult:
    """
    Combined output from detector pipeline.
    """

    speech: SpeechDetectionResult

    whisper: WhisperDetectionResult



class DetectorPipeline:

    def __init__(
        self,
        whisper_detector,
        speech_detector=None,
        mode="direct"
    ):

        self.whisper_detector = whisper_detector
        self.speech_detector = speech_detector

        self.mode = mode


        if mode not in (
            "direct",
            "speech_gate",
            "shadow"
        ):
            raise ValueError(
                f"Unknown processing mode: {mode}"
            )

    def reset(self):
        """Reset stateful detectors at a real audio-stream boundary."""
        for detector in (self.speech_detector, self.whisper_detector):
            if detector is not None and hasattr(detector, "reset"):
                detector.reset()


    def process(self, frame):

        speech_result = SpeechDetectionResult()


        # ---------------------------------
        # Speech stage
        # ---------------------------------

        if self.mode in (
            "speech_gate",
            "shadow"
        ):

            if self.speech_detector is None:
                raise RuntimeError(
                    "Speech detector required"
                )

            speech_result = (
                self.speech_detector.classify(frame)
            )


        # ---------------------------------
        # Whisper stage
        # ---------------------------------

        if self.mode == "speech_gate":

            if speech_result.is_speech:

                whisper_result = (
                    self.whisper_detector.classify(frame)
                )

            else:

                whisper_result = WhisperDetectionResult()


        else:

            # direct
            # shadow

            whisper_result = (
                self.whisper_detector.classify(frame)
            )


        return DetectorPipelineResult(
            speech=speech_result,
            whisper=whisper_result
        )
