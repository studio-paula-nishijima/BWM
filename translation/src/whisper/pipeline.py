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
from typing import Optional

from .models import (
    WhisperDetectionResult,
    SpeechDetectionResult
)


@dataclass
class DetectorPipelineResult:
    """
    Combined output from detector pipeline.
    """

    # None means the configured mode did not run a speech detector.  This is
    # deliberately distinct from a detector result saying ``is_speech=False``.
    speech: Optional[SpeechDetectionResult]

    whisper: WhisperDetectionResult

    processing_mode: str
    speech_gate_open: bool
    whisper_processed: bool



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

        self._summary = {
            "total_frames": 0,
            "speech_positive_frames": 0,
            "whisper_processed_frames": 0,
            "gated_bypassed_frames": 0,
            "whisper_positive_frames": 0,
            "trigger_count": 0,
            "speech_false_whisper_true": 0,
            "speech_true_whisper_false": 0,
            "speech_true_whisper_true": 0,
            "speech_false_whisper_false": 0,
        }


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

        speech_result = None


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

        speech_gate_open = self.mode != "speech_gate"
        whisper_processed = True

        if self.mode == "speech_gate":

            speech_gate_open = speech_result.is_speech

            if speech_gate_open:

                whisper_result = (
                    self.whisper_detector.classify(frame)
                )

            else:

                whisper_result = WhisperDetectionResult()
                whisper_processed = False


        else:

            # direct
            # shadow

            whisper_result = (
                self.whisper_detector.classify(frame)
            )


        result = DetectorPipelineResult(
            speech=speech_result,
            whisper=whisper_result,
            processing_mode=self.mode,
            speech_gate_open=speech_gate_open,
            whisper_processed=whisper_processed,
        )
        self._record_result(result)
        return result

    def _record_result(self, result):
        """Accumulate run-level observability without affecting decisions."""
        summary = self._summary
        summary["total_frames"] += 1
        if result.speech is not None and result.speech.is_speech:
            summary["speech_positive_frames"] += 1
        if result.whisper_processed:
            summary["whisper_processed_frames"] += 1
            if result.whisper.is_whisper:
                summary["whisper_positive_frames"] += 1
        else:
            summary["gated_bypassed_frames"] += 1

        if self.mode == "shadow":
            key = (
                "speech_true" if result.speech.is_speech else "speech_false"
            ) + ("_whisper_true" if result.whisper.is_whisper else "_whisper_false")
            summary[key] += 1

    def record_trigger(self):
        """Record a trigger after the caller's existing trigger logic fires."""
        self._summary["trigger_count"] += 1

    def summary(self):
        """Return a copy so callers cannot alter the accumulated counters."""
        return dict(self._summary)
