"""Stage 3S temporal_v2 classifier; policy confirmation remains in profiles."""
from collections import deque
import numpy as np

from ..features import AudioFeatures
from ..models import WhisperDetectionResult


class TemporalV2WhisperDetector:
    requires_speech_evidence = True

    def __init__(self, sample_rate=16000, **settings):
        self.window = settings.get("rolling_window_frames", 10)
        self.silero_min = settings.get("silero_median_min", .0003)
        self.silero_max = settings.get("silero_median_max", .5)
        self.low_std_min = settings.get("low_proportion_std_min", .05)
        self.low_max = settings.get("low_proportion_max", .85)
        self.zcr_std_min = settings.get("zcr_std_min", .020)
        self.activity_window = settings.get("acoustic_activity_window_frames", 5)
        self.activity_rms_min = settings.get("acoustic_activity_rms_min", 5.5e-5)
        self.context_enabled = bool(settings.get("context_enabled", False))
        self.context_window = settings.get("context_window_frames", 50)
        self.context_threshold = settings.get("context_silero_threshold", .10)
        self.context_min = settings.get("context_min_frames", 5)
        self.features = AudioFeatures(sample_rate=sample_rate, rolling_window_frames=self.window)
        self.reset()

    def reset(self):
        self.features.reset()
        self.silero = deque(maxlen=self.window)
        self.context = deque(maxlen=self.context_window)
        self.activity = deque(maxlen=self.activity_window)
        self.run = 0

    def classify(self, frame, speech_result=None):
        if speech_result is None:
            raise RuntimeError("temporal_v2 requires current Silero speech evidence")
        values = self.features.extract(frame, analysis_full=False)
        self.activity.append(float(values["acoustic_rms"]))
        acoustic_activity = float(np.mean(self.activity))
        acoustic_activity_ok = acoustic_activity >= self.activity_rms_min
        probability = float(speech_result.speech_probability)
        self.silero.append(probability)
        self.context.append(probability >= self.context_threshold)
        full = len(self.silero) == self.window
        median = float(np.median(self.silero)) if full else None
        low_std, zcr_std = values["low_proportion_std"], values["zcr_std"]
        min_pass = None if not full else median >= self.silero_min
        max_pass = None if not full else median <= self.silero_max
        low_std_pass = None if not full else low_std >= self.low_std_min
        low_max_pass = values["low_proportion"] <= self.low_max
        zcr_pass = None if not full else zcr_std >= self.zcr_std_min
        candidate = bool(acoustic_activity_ok and full and min_pass and max_pass and low_std_pass and low_max_pass and zcr_pass)
        self.run = self.run + 1 if candidate else 0
        context_count = int(sum(self.context))
        context_active = self.context_enabled and context_count >= self.context_min
        return WhisperDetectionResult(
            is_whisper=candidate, raw_score=int(candidate), whisper_probability=0.0,
            rms=values["rms"], zcr=values["zcr"], band_energy_low=values["band_low"], band_energy_mid=values["band_mid"], band_energy_high=values["band_high"],
            total_band_energy=values["total_band_energy"], low_proportion=values["low_proportion"], mid_proportion=values["mid_proportion"], high_proportion=values["high_proportion"],
            low_proportion_std=low_std, zcr_std=zcr_std, temporal_v2_window_full=full, temporal_v2_silero_median=median,
            temporal_v2_silero_min_pass=min_pass, temporal_v2_silero_max_pass=max_pass, temporal_v2_low_proportion_std_pass=low_std_pass,
            temporal_v2_low_proportion_max_pass=low_max_pass, temporal_v2_zcr_std_pass=zcr_pass, temporal_v2_raw_is_whisper=candidate,
            temporal_v2_qualifying_run=self.run, temporal_v2_context_enabled=self.context_enabled,
            temporal_v2_context_high_silero_count=context_count if self.context_enabled else None,
            temporal_v2_context_active=context_active if self.context_enabled else None,
            temporal_v2_context_window_frames=self.context_window,
            temporal_v2_context_silero_threshold=self.context_threshold,
            temporal_v2_context_min_frames=self.context_min,
            temporal_v2_acoustic_activity=acoustic_activity, temporal_v2_acoustic_activity_ok=acoustic_activity_ok,
            temporal_v2_acoustic_activity_window_frames=self.activity_window, temporal_v2_acoustic_activity_rms_min=self.activity_rms_min,
            whisper_classifier_implementation="temporal_v2",
        )
