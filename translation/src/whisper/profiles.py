"""Detector-profile composition and temporal trigger confirmation policy."""

from dataclasses import dataclass


PROFILE_NAMES = ("webrtc_assisted_temporal", "temporal_only", "analysis_full")


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

    def update(self, temporal_result, webrtc_result=None):
        candidate = bool(temporal_result.temporal_v1_raw_is_whisper)
        if not candidate:
            self._triggered_this_run = False

        # ``analysis_full`` does not make the WebRTC result the primary speech
        # decision, but it intentionally reconstructs this same mode-0 gate so
        # that its logged trigger policy is directly comparable with the
        # assisted profile.
        uses_webrtc_assist = self.profile in ("webrtc_assisted_temporal", "analysis_full")
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

        run = temporal_result.temporal_v1_qualifying_run or 0
        decision = ProfileDecision(
            webrtc_assist_open=self._webrtc_assist_open if uses_webrtc_assist else None,
            webrtc_enter_count=self._webrtc_enter_count if uses_webrtc_assist else None,
            webrtc_exit_count=self._webrtc_exit_count if uses_webrtc_assist else None,
            assisted_confirmation_requirement=self.settings.get("assisted_confirmation_frames"),
            fallback_confirmation_requirement=self.settings["fallback_confirmation_frames"],
            # This is observability, not merely a trigger-crossing value.
            confirmation_requirement=(
                self.settings["assisted_confirmation_frames"]
                if uses_webrtc_assist and self._webrtc_assist_open
                else self.settings["fallback_confirmation_frames"]
            ),
        )
        if not candidate or self._triggered_this_run:
            return decision
        if uses_webrtc_assist and self._webrtc_assist_open and run >= self.settings["assisted_confirmation_frames"]:
            decision.trigger, decision.trigger_route = True, "webrtc_assisted"
        elif run >= self.settings["fallback_confirmation_frames"]:
            decision.trigger, decision.trigger_route = True, "temporal_fallback"
        if decision.trigger:
            self._triggered_this_run = True
        return decision
