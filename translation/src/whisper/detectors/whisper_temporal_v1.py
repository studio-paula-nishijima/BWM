"""Experimental temporal_v1 whisper classifier.

It consumes the current result from the pipeline's single streaming Silero
speech detector; it never performs VAD inference itself.
"""

from collections import deque
import numpy as np

from ..features import AudioFeatures
from ..models import WhisperDetectionResult


class TemporalV1WhisperDetector:
    requires_speech_evidence = True

    def __init__(self, sample_rate=16000, **kwargs):
        self.rolling_window_frames = kwargs.get("rolling_window_frames", 10)
        self.silero_median_min = kwargs.get("silero_median_min", 0.005)
        self.silero_median_max = kwargs.get("silero_median_max", 0.50)
        self.low_proportion_std_min = kwargs.get("low_proportion_std_min", 0.05)
        self.confirmation_frames = kwargs.get("confirmation_frames", 20)
        self.features = AudioFeatures(sample_rate=sample_rate, rolling_window_frames=self.rolling_window_frames)
        self.reset()

    def reset(self):
        self._silero_history = deque(maxlen=self.rolling_window_frames)
        self._qualifying_run = 0
        self.features.reset()

    def classify(self, frame, speech_result=None):
        if speech_result is None:
            raise RuntimeError("temporal_v1 requires current Silero speech evidence")
        values = self.features.extract(frame)
        probability = speech_result.speech_probability
        self._silero_history.append(probability)
        full = len(self._silero_history) == self.rolling_window_frames
        median = float(np.median(self._silero_history)) if full else None
        low_std = values["low_proportion_std"]
        min_pass = None if not full else median >= self.silero_median_min
        max_pass = None if not full else median <= self.silero_median_max
        variation_pass = None if not full else low_std >= self.low_proportion_std_min
        raw = bool(full and min_pass and max_pass and variation_pass)
        self._qualifying_run = self._qualifying_run + 1 if raw else 0
        return WhisperDetectionResult(
            is_whisper=raw, whisper_probability=0.0, raw_score=int(raw),
            rms=values["rms"], zcr=values["zcr"], entropy=values["entropy"], voicing=values["voicing"], hnr=values["hnr"],
            spectral_centroid=values["centroid"], band_energy_low=values["band_low"], band_energy_mid=values["band_mid"], band_energy_high=values["band_high"],
            band_ratio_low=values["ratio_low"], band_ratio_mid=values["ratio_mid"], band_ratio_high=values["ratio_high"],
            total_band_energy=values["total_band_energy"], low_proportion=values["low_proportion"], mid_proportion=values["mid_proportion"], high_proportion=values["high_proportion"],
            low_proportion_std=low_std, mid_proportion_std=values["mid_proportion_std"], high_proportion_std=values["high_proportion_std"],
            zcr_std=values["zcr_std"], entropy_std=values["entropy_std"], spectral_centroid_std=values["centroid_std"], spectral_flux=values["spectral_flux"],
            cepstral_peak_prominence=values["cepstral_peak_prominence"], spectral_slope=values["spectral_slope"], spectral_rolloff=values["spectral_rolloff"], spectral_flatness=values["spectral_flatness"],
            temporal_v1_window_full=full, temporal_v1_silero_median=median, temporal_v1_low_proportion_std=low_std,
            temporal_v1_silero_min_pass=min_pass, temporal_v1_silero_max_pass=max_pass, temporal_v1_low_proportion_std_pass=variation_pass,
            temporal_v1_raw_is_whisper=raw, temporal_v1_is_whisper=raw, temporal_v1_qualifying_run=self._qualifying_run,
            confirmation_frames=self.confirmation_frames, whisper_classifier_implementation="temporal_v1",
        )
