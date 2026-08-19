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
from typing import Dict, Optional

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
    speech_comparison: Optional[SpeechDetectionResult]
    speech_comparisons: Dict[int, SpeechDetectionResult]

    whisper: WhisperDetectionResult

    processing_mode: str
    speech_gate_open: bool
    whisper_processed: bool



class DetectorPipeline:

    def __init__(
        self,
        whisper_detector,
        speech_detector=None,
        mode="direct",
        comparison_whisper_detector=None,
        comparison_whisper_detectors=None,
        comparison_speech_detector=None,
        comparison_speech_detectors=None,
        classifier_implementation="legacy"
    ):

        self.whisper_detector = whisper_detector
        self.speech_detector = speech_detector
        self.comparison_whisper_detector = comparison_whisper_detector
        self.comparison_whisper_detectors = dict(comparison_whisper_detectors or {})
        if comparison_whisper_detector is not None:
            self.comparison_whisper_detectors.setdefault(
                getattr(comparison_whisper_detector, "whisper_classifier_implementation", "comparison"),
                comparison_whisper_detector,
            )
        self.comparison_speech_detector = comparison_speech_detector
        self.comparison_speech_detectors = dict(comparison_speech_detectors or {})
        if comparison_speech_detector is not None and not self.comparison_speech_detectors:
            self.comparison_speech_detectors[getattr(comparison_speech_detector, "aggressiveness", 0)] = comparison_speech_detector
        self.classifier_implementation = classifier_implementation

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
        all_whisper_detectors = (whisper_detector, *self.comparison_whisper_detectors.values())
        if mode == "direct" and any(getattr(detector, "requires_speech_evidence", False) for detector in all_whisper_detectors):
            raise ValueError("Silero-evidence classifiers require speech_gate or shadow mode and cannot run in direct mode")
        if any(getattr(detector, "requires_speech_evidence", False) for detector in all_whisper_detectors) and getattr(speech_detector, "speech_backend", None) == "webrtc":
            raise ValueError("grouped_v1 and temporal_v1 require a primary Silero speech detector")

    def reset(self):
        """Reset stateful detectors at a real audio-stream boundary."""
        for detector in (self.speech_detector, *self.comparison_speech_detectors.values(), self.whisper_detector, *self.comparison_whisper_detectors.values()):
            if detector is not None and hasattr(detector, "reset"):
                detector.reset()


    def process(self, frame):

        speech_result = None


        # ---------------------------------
        # Speech stage
        # ---------------------------------

        needs_speech = any(getattr(detector, "requires_speech_evidence", False) for detector in (self.whisper_detector, *self.comparison_whisper_detectors.values()))
        if self.mode in (
            "speech_gate",
            "shadow"
        ) or needs_speech:

            if self.speech_detector is None:
                raise RuntimeError(
                    "Speech detector required"
                )

            speech_result = (
                self.speech_detector.classify(frame)
            )
            speech_comparisons = {mode: detector.classify(frame) for mode, detector in self.comparison_speech_detectors.items()}
            speech_comparison = speech_comparisons.get(1) or next(iter(speech_comparisons.values()), None)
        else:
            speech_comparison = None
            speech_comparisons = {}


        # ---------------------------------
        # Whisper stage
        # ---------------------------------

        speech_gate_open = self.mode != "speech_gate"
        whisper_processed = True

        if self.mode == "speech_gate" and not getattr(self.whisper_detector, "requires_speech_evidence", False):

            speech_gate_open = speech_result.is_speech

            if speech_gate_open:

                whisper_result = (
                    self._classify(self.whisper_detector, frame, speech_result)
                )

            else:

                whisper_result = WhisperDetectionResult()
                whisper_processed = False


        else:

            # direct
            # shadow

            whisper_result = (
                self._classify(self.whisper_detector, frame, speech_result)
            )

        for comparison_detector in self.comparison_whisper_detectors.values():
            comparison = self._classify(comparison_detector, frame, speech_result)
            if comparison.whisper_classifier_implementation == "grouped_v1":
                whisper_result.grouped_v1_is_whisper = comparison.is_whisper
            elif comparison.whisper_classifier_implementation == "temporal_v1":
                whisper_result.temporal_v1_is_whisper = comparison.is_whisper
            else:
                whisper_result.legacy_is_whisper = comparison.is_whisper
        if whisper_result.whisper_classifier_implementation is None:
            whisper_result.whisper_classifier_implementation = self.classifier_implementation
        if self.classifier_implementation == "legacy":
            whisper_result.legacy_is_whisper = whisper_result.is_whisper
        elif self.classifier_implementation == "grouped_v1":
            whisper_result.grouped_v1_is_whisper = whisper_result.is_whisper
        elif self.classifier_implementation == "temporal_v1":
            whisper_result.temporal_v1_is_whisper = whisper_result.is_whisper
        elif self.classifier_implementation == "temporal_v2":
            whisper_result.temporal_v2_raw_is_whisper = whisper_result.is_whisper


        result = DetectorPipelineResult(
            speech=speech_result,
            speech_comparison=speech_comparison,
            speech_comparisons=speech_comparisons,
            whisper=whisper_result,
            processing_mode=self.mode,
            speech_gate_open=speech_gate_open,
            whisper_processed=whisper_processed,
        )
        self._record_result(result)
        return result

    @staticmethod
    def _classify(detector, frame, speech_result):
        if getattr(detector, "requires_speech_evidence", False):
            return detector.classify(frame, speech_result=speech_result)
        return detector.classify(frame)

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
