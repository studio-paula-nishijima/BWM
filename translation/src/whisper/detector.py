import collections

from .features import WhisperFeatures
from .models import DetectionResult
from .temporal import TemporalSmoother


class WhisperDetector:

    def __init__(
        self,
        sample_rate=16000,
        rms_min=0.005,
        rms_max=0.1,
        zcr_min=0.05,
        zcr_max=0.3,
        entropy_min=4.5,
        decision_window=10,
        trigger_ratio=0.6
    ):

        self.rms_min = rms_min
        self.rms_max = rms_max

        self.zcr_min = zcr_min
        self.zcr_max = zcr_max

        self.entropy_min = entropy_min


        self.features = WhisperFeatures(
            sample_rate=sample_rate
        )


        self.temporal = TemporalSmoother(
            window_size=decision_window,
            trigger_ratio=trigger_ratio
        )


    def classify(self, frame):
    
        values = self.features.extract(frame)
    
        rms = values["rms"]
        zcr = values["zcr"]
        entropy = values["entropy"]
    
        score = 0
    
        feature_scores = {}
    
        # -----------------------------
        # Existing scoring logic
        # -----------------------------
    
        if self.rms_min < rms < self.rms_max:
            score += 1
            feature_scores["rms"] = 1
        else:
            feature_scores["rms"] = 0
    
    
        if self.zcr_min < zcr < self.zcr_max:
            score += 1
            feature_scores["zcr"] = 1
        else:
            feature_scores["zcr"] = 0
    
    
        if entropy > self.entropy_min:
            score += 1
            feature_scores["entropy"] = 1
        else:
            feature_scores["entropy"] = 0
    
    
        raw_whisper = score >= 2
    
    
        smoothed_whisper = self.temporal.update(
            raw_whisper
        )
    
    
        result = DetectionResult(
    
            is_whisper=smoothed_whisper,
    
            # Stage 1:
            # retain binary behaviour.
            # Probability model comes later.
            whisper_probability=(
                score / 3.0
            ),
    
            # Existing core features
            rms=rms,
            zcr=zcr,
            entropy=entropy,
    
            # New observational features only
            spectral_centroid=values["centroid"],
    
            band_energy_low=values["band_low"],
            band_energy_mid=values["band_mid"],
            band_energy_high=values["band_high"],
    
            band_ratio_low=values["ratio_low"],
            band_ratio_mid=values["ratio_mid"],
            band_ratio_high=values["ratio_high"],
    
            raw_score=score,
    
            feature_scores=feature_scores
        )
    
    
        return result
    
