"""Provisional grouped whisper classifier; intentionally score-based, not probabilistic."""

from collections import deque

import numpy as np

from ..features import AudioFeatures
from ..models import WhisperDetectionResult


class GroupedV1WhisperDetector:
    """Stateful Stage 1 Silero gate plus independent grouped feature evidence."""

    requires_speech_evidence = True

    def __init__(self, sample_rate=16000, **kwargs):
        self.features = AudioFeatures(sample_rate=sample_rate)
        self.stage1_silero_probability_min = kwargs.get("stage1_silero_probability_min", 0.005)
        self.stage1_enter_frames = kwargs.get("stage1_enter_consecutive_frames", 3)
        self.stage1_exit_frames = kwargs.get("stage1_exit_consecutive_frames", 10)
        self.zcr_threshold = kwargs.get("grouped_zcr_threshold", 0.080)
        self.centroid_threshold = kwargs.get("grouped_centroid_threshold_hz", 1280.0)
        self.entropy_threshold = kwargs.get("grouped_entropy_threshold", 2.60)
        self.low_proportion_threshold = kwargs.get("grouped_low_proportion_threshold", 0.80)
        self.silero_window_frames = kwargs.get("silero_window_frames", 10)
        self.high_silero_threshold = kwargs.get("high_silero_threshold", 0.50)
        self.high_silero_required_frames = kwargs.get("high_silero_required_frames", 3)
        self.reset()

    def reset(self):
        self._candidate = False
        self._enter_count = 0
        self._exit_count = 0
        self._silero_history = deque(maxlen=self.silero_window_frames)
        self._high_silero_count = 0
        self._stage2_count = 0

    def classify(self, frame, speech_result=None):
        if speech_result is None:
            raise RuntimeError("grouped_v1 requires current Silero speech evidence")
        probability = speech_result.speech_probability
        low_pass = probability >= self.stage1_silero_probability_min
        if self._candidate:
            self._enter_count = 0
            self._exit_count = 0 if low_pass else self._exit_count + 1
            if self._exit_count >= self.stage1_exit_frames:
                self._candidate, self._exit_count = False, 0
        else:
            self._exit_count = 0
            self._enter_count = self._enter_count + 1 if low_pass else 0
            if self._enter_count >= self.stage1_enter_frames:
                self._candidate, self._enter_count = True, 0

        self._silero_history.append(probability)
        full_window = len(self._silero_history) == self.silero_window_frames
        median = float(np.median(self._silero_history)) if full_window else None
        high_raw = bool(full_window and median > self.high_silero_threshold)
        self._high_silero_count = self._high_silero_count + 1 if high_raw else 0
        high_evidence = self._high_silero_count >= self.high_silero_required_frames

        values = self.features.extract(frame)
        low, mid, high = values["band_low"], values["band_mid"], values["band_high"]
        total = low + mid + high
        denominator = max(total, 1e-12)
        low_p, mid_p, high_p = low / denominator, mid / denominator, high / denominator
        zcr_pass = values["zcr"] >= self.zcr_threshold
        centroid_pass = values["centroid"] >= self.centroid_threshold
        group_a = zcr_pass or centroid_pass
        group_b = values["entropy"] >= self.entropy_threshold
        group_c = low_p < self.low_proportion_threshold
        group_count = int(group_a) + int(group_b) + int(group_c)
        penalty = int(high_evidence)
        effective = group_count - penalty
        raw = effective >= 2
        stage2 = self._candidate and raw
        self._stage2_count = self._stage2_count + 1 if stage2 else 0
        return WhisperDetectionResult(
            is_whisper=stage2, raw_score=group_count, rms=values["rms"], zcr=values["zcr"], entropy=values["entropy"],
            spectral_centroid=values["centroid"], band_energy_low=low, band_energy_mid=mid, band_energy_high=high,
            band_ratio_low=values["ratio_low"], band_ratio_mid=values["ratio_mid"], band_ratio_high=values["ratio_high"],
            stage1_silero_threshold=self.stage1_silero_probability_min, stage1_silero_low_pass=low_pass,
            stage1_enter_count=self._enter_count, stage1_exit_count=self._exit_count, stage1_candidate=self._candidate,
            zcr_threshold=self.zcr_threshold, zcr_pass=zcr_pass, centroid_threshold=self.centroid_threshold,
            centroid_pass=centroid_pass, group_a_pass=group_a, entropy_threshold=self.entropy_threshold,
            group_b_pass=group_b, total_band_energy=total, low_proportion=low_p, mid_proportion=mid_p,
            high_proportion=high_p, low_proportion_threshold=self.low_proportion_threshold, group_c_pass=group_c,
            silero_rolling_median=median, high_silero_threshold=self.high_silero_threshold, high_silero_raw=high_raw,
            high_silero_count=self._high_silero_count, high_silero_normal_evidence=high_evidence, silero_penalty=penalty,
            group_count=group_count, effective_group_score=effective, grouped_v1_raw_is_whisper=raw,
            stage2_is_whisper=stage2, stage2_consecutive_count=self._stage2_count,
            grouped_v1_is_whisper=stage2, whisper_classifier_implementation="grouped_v1",
        )
