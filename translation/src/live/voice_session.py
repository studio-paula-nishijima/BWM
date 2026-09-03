"""Voice-owned active-period and graceful quiescence policy."""
from __future__ import annotations

import threading

from live.voice_runtime import VoiceState


class VoiceSessionController:
    """Keep Voice process/resources policy separate from interaction lifecycle."""
    def __init__(self, coordinator, *, active_period_seconds=600, initially_active=True,
                 stop_asr_when_quiescent=True, emit=print, timer_factory=threading.Timer):
        if active_period_seconds <= 0:
            raise ValueError("Voice active_period_seconds must be positive")
        self.coordinator = coordinator
        self.active_period_seconds = float(active_period_seconds)
        self.initially_active = initially_active
        self.stop_asr_when_quiescent = stop_asr_when_quiescent
        self.emit, self._timer_factory = emit, timer_factory
        self._timer = None
        self.quiescence_requested = not initially_active
        self.quiescent = not initially_active
        self.coordinator.lifecycle.add_transition_observer(self._on_lifecycle_transition)

    @property
    def admitting_interactions(self):
        return not self.quiescence_requested and not self.quiescent

    def start(self):
        if self.initially_active:
            self.coordinator.start()
            self._arm_timer("active")
        else:
            self.emit("[WhisperSession] quiescent at startup")

    def activation_received(self, state, _event=None):
        if state == "active":
            if self.quiescent:
                self.emit("[WhisperSession] quiescent -> active reason=translation_active; reinitializing")
                self.quiescent = self.quiescence_requested = False
                self.coordinator.reactivate()
            else:
                self.quiescence_requested = False
                self.emit("[WhisperSession] active -> active reason=translation_active; timer_reset")
            self._arm_timer("active")
        elif state == "inactive":
            self.request_quiescence("translation_inactive")

    def request_quiescence(self, reason):
        if self.quiescence_requested or self.quiescent:
            return
        self.quiescence_requested = True
        self._cancel_timer()
        self.emit(f"[WhisperSession] active -> quiescence_requested reason={reason}")
        if self.coordinator.interaction_admitted:
            self.emit("[WhisperSession] waiting_for_interaction_completion")
            return
        self._enter_quiescent()

    def _on_lifecycle_transition(self, _before, after):
        if self.quiescence_requested and after is VoiceState.LISTENING and not self.coordinator.capture.is_capturing:
            self._enter_quiescent()

    def _enter_quiescent(self):
        if self.quiescent:
            return
        self.quiescent = True
        if self.stop_asr_when_quiescent:
            self.coordinator.quiesce()
        self.emit("[WhisperSession] quiescence_requested -> quiescent")

    def _arm_timer(self, _reason):
        self._cancel_timer()
        self._timer = self._timer_factory(self.active_period_seconds, self._expired)
        self._timer.daemon = True
        self._timer.start()
        self.emit(f"[WhisperSession] active; timer {self.active_period_seconds:g} s")

    def _expired(self):
        self.request_quiescence("timer_expired")

    def _cancel_timer(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def shutdown(self):
        self._cancel_timer()
