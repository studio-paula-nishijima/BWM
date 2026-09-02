"""Detector-profile composition and temporal trigger confirmation policy."""

from dataclasses import dataclass
from collections import deque
from statistics import median


PROFILE_NAMES = ("webrtc_assisted_temporal", "temporal_only", "analysis_full", "temporal_v2_context", "temporal_v2_recall")


@dataclass
class ProfileDecision:
    trigger: bool = False
    trigger_route: str = None
    confirmation_requirement: int = None
    webrtc_assist_open: bool = None
    webrtc_enter_count: int = None
    webrtc_exit_count: int = None
    assisted_confirmation_requirement: int = None
    fallback_confirmation_requirement: int = None
    context_confirmation_requirement: int = None
    silero_selection_value: float = None


class TemporalProfilePolicy:
    """Stateful, one-trigger-per-contiguous-temporal-run profile policy."""

    def __init__(self, profile, settings):
        if profile not in PROFILE_NAMES:
            raise ValueError("Unknown detector profile; choose " + ", ".join(PROFILE_NAMES))
        self.profile = profile
        self.settings = settings
        self.reset()

    def reset(self):
        self._webrtc_assist_open = False
        self._webrtc_enter_count = 0
        self._webrtc_exit_count = 0
        self._triggered_this_run = False
        self._selection_values = deque(maxlen=10)

    def update(self, temporal_result, webrtc_result=None):
        candidate = bool(temporal_result.temporal_v2_raw_is_whisper if temporal_result.temporal_v2_raw_is_whisper is not None else temporal_result.temporal_v1_raw_is_whisper)
        if not candidate:
            self._triggered_this_run = False
            self._selection_values.clear()
        elif temporal_result.silero_probability is not None:
            # Reuse the one authoritative per-frame Silero inference.  The
            # window intentionally begins at this contiguous qualifying run.
            self._selection_values.append(float(temporal_result.silero_probability))

        # ``analysis_full`` does not make the WebRTC result the primary speech
        # decision, but it intentionally reconstructs this same mode-0 gate so
        # that its logged trigger policy is directly comparable with the
        # assisted profile.
        uses_webrtc_assist = self.profile in ("webrtc_assisted_temporal", "analysis_full", "temporal_v2_context", "temporal_v2_recall")
        if uses_webrtc_assist:
            positive = bool(webrtc_result and webrtc_result.is_speech)
            if self._webrtc_assist_open:
                self._webrtc_exit_count = 0 if positive else self._webrtc_exit_count + 1
                if self._webrtc_exit_count >= self.settings["webrtc_exit_frames"]:
                    self._webrtc_assist_open = False
                    self._webrtc_exit_count = 0
            else:
                self._webrtc_enter_count = self._webrtc_enter_count + 1 if positive else 0
                if self._webrtc_enter_count >= self.settings["webrtc_enter_frames"]:
                    self._webrtc_assist_open = True
                    self._webrtc_enter_count = 0

        run = temporal_result.temporal_v2_qualifying_run if temporal_result.temporal_v2_qualifying_run is not None else (temporal_result.temporal_v1_qualifying_run or 0)
        context_active = bool(getattr(temporal_result, "temporal_v2_context_active", False))
        is_v2 = self.profile in ("temporal_v2_context", "temporal_v2_recall")
        if is_v2 and context_active:
            requirement, route = self.settings["context_confirmation_frames"], "context"
        elif uses_webrtc_assist and self._webrtc_assist_open:
            requirement, route = self.settings["assisted_confirmation_frames"], "webrtc_assisted"
        else:
            requirement, route = self.settings["fallback_confirmation_frames"], "temporal_fallback"
        decision = ProfileDecision(
            webrtc_assist_open=self._webrtc_assist_open if uses_webrtc_assist else None,
            webrtc_enter_count=self._webrtc_enter_count if uses_webrtc_assist else None,
            webrtc_exit_count=self._webrtc_exit_count if uses_webrtc_assist else None,
            assisted_confirmation_requirement=self.settings.get("assisted_confirmation_frames"),
            fallback_confirmation_requirement=self.settings["fallback_confirmation_frames"],
            context_confirmation_requirement=self.settings.get("context_confirmation_frames"),
            # This is observability, not merely a trigger-crossing value.
            confirmation_requirement=requirement,
        )
        if not candidate or self._triggered_this_run:
            return decision
        if run >= requirement:
            decision.trigger, decision.trigger_route = True, route
        if decision.trigger:
            self._triggered_this_run = True
            if len(self._selection_values) == 10:
                decision.silero_selection_value = float(median(self._selection_values))
        return decision
