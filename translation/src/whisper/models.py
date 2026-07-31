from dataclasses import dataclass, field
from typing import Dict


@dataclass
class DetectionResult:
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

    feature_scores: Dict[str, float] = field(
        default_factory=dict
    )
