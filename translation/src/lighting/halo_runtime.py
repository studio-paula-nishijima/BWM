"""Non-critical Translation-side Halo 60x runtime policy."""
from __future__ import annotations

import logging
import math
import threading
import time

from .halo60x_demo import Halo60xState, state_to_dmx_channels
from .ola_client import OLAUniverseClient

LOG = logging.getLogger(__name__)

class HaloLightingController:
    """Base state plus a non-overlapping temporary gesture, independent of GPIO."""
    def __init__(self, config, *, clock=time.monotonic, sleep=time.sleep, ola_client=None, emit=print):
        self.config, self.clock, self.sleep, self.emit = dict(config or {}), clock, sleep, emit
        self.enabled = bool(self.config.get("enabled", False))
        self.base = Halo60xState(float(self.config.get("active_brightness_percent", 60)), float(self.config.get("active_cct_kelvin", 2700)))
        self._runoff_config = dict(self.config.get("runoff_brightness", {}))
        self._runoff_enabled = bool(self._runoff_config.get("enabled", False))
        self._runoff_activity = None
        self._runoff_target = self.base.brightness_percent
        self._last_smoothing_at = self.clock()
        self._policy_active = False
        self.blackout = Halo60xState(0, self.base.cct_kelvin)
        self.address = int(self.config.get("start_address", 1))
        self.universe = int(self.config.get("universe", 1))
        self.interval = float(self.config.get("frame_interval_seconds", .1))
        self._ola = ola_client
        self._next_frame = 0.0
        self._retry_at = 0.0
        self._base_fade = None
        self._gesture_started = None
        self._gesture_until = 0.0
        self._last_gesture = float("-inf")
        self._current = self.blackout
        self._fade_worker = None

    def activate(self):
        now = self.clock()
        self._policy_active = True
        self._last_smoothing_at = now
        self._base_fade = ("activation", now, self._current, float(self.config.get("activation_fade_seconds", 4.0)))
        self._gesture_started = None

    @property
    def activation_delay_seconds(self):
        """Configured base-fade time before Translation admits playback."""
        return float(self.config.get("activation_fade_seconds", 4.0)) if self.enabled else 0.0

    def deactivate(self):
        now = self.clock()
        self._advance_runoff_base(now)
        self._policy_active = False
        self._gesture_started = None
        self._base_fade = ("deactivation", now, self._current, float(self.config.get("deactivation_fade_seconds", 4.0)))

    def set_runoff_activity(self, activity):
        """Update the lighting target from a read-only normalized runoff mean."""
        activity = min(1.0, max(0.0, float(activity)))
        low = 100.0 * float(self._runoff_config.get("min_brightness", 0.50))
        high = 100.0 * float(self._runoff_config.get("max_brightness", 0.70))
        self._runoff_activity = activity
        self._runoff_target = low + activity * (high - low)
        if self._runoff_enabled and not self._policy_active:
            # Before activation there is no visible output to smooth.  Seed the
            # startup fade with the selected session's current runoff state.
            self.base = Halo60xState(self._runoff_target, self.base.cct_kelvin)
        LOG.debug("Halo runoff activity=%.4f target=%.2f%% current=%.2f%%",
                  activity, self._runoff_target, self.base.brightness_percent)

    def deactivate_async(self):
        """Continue a normal fade after the session loop enters idle."""
        self.deactivate()
        if not self.enabled or (self._fade_worker and self._fade_worker.is_alive()):
            return
        self._fade_worker = threading.Thread(target=self._finish_deactivation, daemon=True)
        self._fade_worker.start()

    def trigger_interaction(self):
        now = self.clock()
        cooldown = float(self.config.get("gesture_cooldown_seconds", 7.0))
        if not self.enabled or not self.config.get("whisper_gesture", {}).get("enabled", True) or now - self._last_gesture < cooldown:
            return False
        self._last_gesture, self._gesture_started = now, now
        self._gesture_until = now + float(self.config.get("whisper_gesture", {}).get("duration_seconds", 7.0))
        return True

    def step(self):
        if not self.enabled:
            return
        now = self.clock()
        state = self._state_at(now)
        self._current = state
        if now >= self._next_frame:
            self._next_frame = now + self.interval  # drop stale frames when I/O is slow
            self._send(state)

    def shutdown(self):
        """Best-effort controlled fade; failures are isolated from GPIO shutdown."""
        self.deactivate()
        deadline = self.clock() + float(self.config.get("deactivation_fade_seconds", 4.0))
        while self.enabled and self.clock() < deadline:
            self.step()
            self.sleep(min(self.interval, max(0, deadline - self.clock())))
        self._current = self.blackout
        self._send(self.blackout)
        self._close()

    def _finish_deactivation(self):
        deadline = self.clock() + float(self.config.get("deactivation_fade_seconds", 4.0))
        while self.clock() < deadline:
            self.step()
            self.sleep(self.interval)
        self._current = self.blackout
        self._send(self.blackout)

    def _state_at(self, now):
        self._advance_runoff_base(now)
        base = self.base
        if self._base_fade:
            kind, started, start, duration = self._base_fade
            progress = 1.0 if duration == 0 else min(1.0, (now - started) / duration)
            end = self.base if kind == "activation" else self.blackout
            base = self._interpolate(start, end, progress)
            if progress >= 1:
                self._base_fade = None
        if self._gesture_started is None or now >= self._gesture_until:
            self._gesture_started = None
            return base
        gesture = self.config.get("whisper_gesture", {})
        duration, pulses = float(gesture.get("duration_seconds", 7.0)), int(gesture.get("pulse_count", 3))
        phase = ((now - self._gesture_started) / duration * pulses) % 1.0
        amount = 1.0 - abs(2.0 * phase - 1.0)  # symmetric triangular smooth pulse
        target = Halo60xState(float(gesture.get("target_brightness_percent", 50)), float(gesture.get("target_cct_kelvin", 6500)))
        return self._interpolate(base, target, amount)

    def _advance_runoff_base(self, now):
        if not self._runoff_enabled or not self._policy_active or self._runoff_activity is None:
            self._last_smoothing_at = now
            return
        elapsed = max(0.0, now - self._last_smoothing_at)
        self._last_smoothing_at = now
        smoothing = float(self._runoff_config.get("smoothing_seconds", 5.0))
        amount = 1.0 if smoothing <= 0 else -math.expm1(-elapsed / smoothing)
        brightness = self.base.brightness_percent + (self._runoff_target - self.base.brightness_percent) * amount
        self.base = Halo60xState(brightness, self.base.cct_kelvin)

    @staticmethod
    def _interpolate(start, end, amount):
        return Halo60xState(start.brightness_percent + (end.brightness_percent - start.brightness_percent) * amount,
                            start.cct_kelvin + (end.cct_kelvin - start.cct_kelvin) * amount)

    def _send(self, state):
        if self.clock() < self._retry_at:
            return
        try:
            if self._ola is None:
                self._ola = OLAUniverseClient(self.universe, refresh_hz=self.config.get("ola_refresh_hz", 30),
                                              retry_seconds=self.config.get("retry_seconds", 5), emit=self.emit)
            # OLA/FTDI sends only through the fixture's final used slot.  The
            # rpi05 hardware path was proven with this three-slot form at
            # address 1; padding to all 512 slots prevented fixture output.
            frame = bytearray(self.address + 2)
            frame[self.address - 1:self.address + 2] = bytes(state_to_dmx_channels(state))
            self._ola.send(frame)
        except Exception as exc:
            LOG.warning("Halo DMX unavailable: %s", exc)
            self.emit(f"[Halo] unavailable; continuing Translation: {exc}")
            self._retry_at = self.clock() + float(self.config.get("retry_seconds", 5.0))

    def _close(self):
        if self._ola is not None:
            try: self._ola.close()
            except Exception: pass
