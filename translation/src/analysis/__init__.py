"""Offline labelled-WAV analysis.  This package never participates in live detection."""

from .labelled_wav import (
    AnnotationValidationError,
    analyse_triplets,
    join_frames_to_annotations,
    load_annotations,
    utterance_metadata_summary,
)
from .asr_evaluation import ASRBackend, ASRResult, AudioSegment, FasterWhisperBackend

__all__ = ["AnnotationValidationError", "analyse_triplets", "join_frames_to_annotations", "load_annotations", "utterance_metadata_summary", "ASRBackend", "ASRResult", "AudioSegment", "FasterWhisperBackend"]
