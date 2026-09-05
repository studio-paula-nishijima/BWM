"""Non-critical Translation-side Halo 60x runtime policy."""
from __future__ import annotations

import logging
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
        self._base_fade = (self.clock(), self._current, self.base, float(self.config.get("activation_fade_seconds", 4.0)))
        self._gesture_started = None

    def deactivate(self):
        self._gesture_started = None
        self._base_fade = (self.clock(), self._current, self.blackout, float(self.config.get("deactivation_fade_seconds", 4.0)))

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
        base = self.base
        if self._base_fade:
            started, start, end, duration = self._base_fade
            progress = 1.0 if duration == 0 else min(1.0, (now - started) / duration)
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
            frame = bytearray(512)
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
