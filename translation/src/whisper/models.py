from dataclasses import dataclass, field
from typing import Dict


@dataclass
class WhisperDetectionResult:
    """
    Container for a single analysed audio frame.

    Stage 1:
    Only rms, zcr and entropy are populated.
    Additional fields are placeholders for later detector versions.
    """

    # -----------------------------
    # Decision outputs
    # -----------------------------

    is_whisper: bool = False
    whisper_probability: float = 0.0
    trigger_ready: bool = False


    # -----------------------------
    # acoustic features
    # -----------------------------

    rms: float = 0.0
    zcr: float = 0.0
    entropy: float = 0.0

    voicing: float = 0.0
    hnr: float = 0.0
    spectral_centroid: float = 0.0

    band_energy_low: float = 0.0
    band_energy_mid: float = 0.0
    band_energy_high: float = 0.0
    
    band_ratio_low: float = 0.0
    band_ratio_mid: float = 0.0
    band_ratio_high: float = 0.0

    temporal_score: float = 0.0
    formant_score: float = 0.0


    # -----------------------------
    # Debug / analysis
    # -----------------------------

    raw_score: int = 0

    # Stage 3K grouped_v1 observability.  ``None`` means the relevant backend
    # did not run (rather than a fabricated negative value).
    stage1_silero_threshold: float = None
    stage1_silero_low_pass: bool = None
    stage1_enter_count: int = None
    stage1_exit_count: int = None
    stage1_candidate: bool = None
    zcr_threshold: float = None
    zcr_pass: bool = None
    centroid_threshold: float = None
    centroid_pass: bool = None
    group_a_pass: bool = None
    entropy_threshold: float = None
    group_b_pass: bool = None
    total_band_energy: float = None
    low_proportion: float = None
    mid_proportion: float = None
    high_proportion: float = None
    low_proportion_threshold: float = None
    group_c_pass: bool = None
    silero_rolling_median: float = None
    high_silero_threshold: float = None
    high_silero_raw: bool = None
    high_silero_count: int = None
    high_silero_normal_evidence: bool = None
    silero_penalty: int = None
    group_count: int = None
    effective_group_score: int = None
    grouped_v1_raw_is_whisper: bool = None
    stage2_is_whisper: bool = None
    stage2_consecutive_count: int = None
    legacy_is_whisper: bool = None
    grouped_v1_is_whisper: bool = None
    whisper_classifier_implementation: str = None

    feature_scores: Dict[str, float] = field(
        default_factory=dict
    )
    
@dataclass
class SpeechDetectionResult:
    """
    Result from speech presence classification.

    Answers:
        "Is this human speech?"
    """

    is_speech: bool = False

    speech_probability: float = 0.0

    features: Dict[str, float] = field(
        default_factory=dict
    )
