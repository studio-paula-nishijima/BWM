from dataclasses import dataclass, field
from typing import Dict, Optional


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
    confirmation_frames: int = None

    # Stage 3L temporal_v1 decision observability.
    temporal_v1_window_full: bool = None
    temporal_v1_silero_median: float = None
    temporal_v1_low_proportion_std: float = None
    temporal_v1_silero_min_pass: bool = None
    temporal_v1_silero_max_pass: bool = None
    temporal_v1_low_proportion_std_pass: bool = None
    temporal_v1_low_proportion_max: float = None
    temporal_v1_low_proportion_max_pass: bool = None
    temporal_v1_raw_is_whisper: bool = None
    temporal_v1_is_whisper: bool = None
    temporal_v1_qualifying_run: int = None

    # Analysis-only Stage 3L acoustic/temporal observability.  ``None`` is
    # used when history required by a measurement is unavailable.
    low_proportion_std: float = None
    mid_proportion_std: float = None
    high_proportion_std: float = None
    zcr_std: float = None
    entropy_std: float = None
    spectral_centroid_std: float = None
    spectral_flux: float = None
    spectral_rolloff: float = None
    spectral_flatness: float = None
    spectral_slope: float = None
    cepstral_peak_prominence: float = None

    detector_profile: str = None
    webrtc_assist_open: bool = None
    webrtc_assist_enter_count: int = None
    webrtc_assist_exit_count: int = None
    temporal_candidate: bool = None
    temporal_qualifying_run: int = None
    confirmation_requirement: int = None
    threshold_crossing_route: str = None
    trigger_route: str = None
    trigger_suppression_reason: str = None
    assisted_confirmation_requirement: int = None
    fallback_confirmation_requirement: int = None

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

    # ``None`` means a backend has no continuous probability (WebRTC VAD).
    speech_probability: Optional[float] = 0.0

    features: Dict[str, float] = field(
        default_factory=dict
    )
