"""Persistent OLA-universe output; application code never owns a serial DMX device."""
from __future__ import annotations

import array
import logging
import threading
import time

LOG = logging.getLogger(__name__)


class OLAUniverseClient:
    """Keep one OLA source connected and refresh its latest universe frame."""
    def __init__(self, universe, *, refresh_hz=30, retry_seconds=5, wrapper_factory=None, emit=print):
        self.universe, self.refresh_hz = int(universe), float(refresh_hz)
        self._wrapper_factory, self._emit = wrapper_factory, emit
        self._frame, self._lock = bytearray(512), threading.Lock()
        self._wrapper = self._thread = None
        self._started = False
        self._closed = False
        self._retry_seconds, self._retry_at = float(retry_seconds), 0.0

    def send(self, frame):
        if len(frame) != 512:
            raise ValueError("OLA universe frames must contain 512 channels")
        with self._lock:
            self._frame[:] = frame
        if not self._started and time.monotonic() >= self._retry_at:
            self._start()

    def close(self):
        if self._closed:
            return
        self._closed = True
        with self._lock:
            self._frame[:] = b"\0" * 512
        # A final scheduled blackout is sent before withdrawing this source.
        if self._wrapper is not None:
            try:
                self._wrapper.AddEvent(0, self._blackout_and_stop)
            except Exception:
                pass

    def _start(self):
        self._started = True
        self._thread = threading.Thread(target=self._run, name="ola-halo", daemon=True)
        self._thread.start()

    def _run(self):
        try:
            if self._wrapper_factory is None:
                from ola.ClientWrapper import ClientWrapper
                wrapper = ClientWrapper()
            else:
                wrapper = self._wrapper_factory()
            self._wrapper = wrapper
            wrapper.AddEvent(0, self._tick)
            wrapper.Run()
        except Exception as exc:
            self._started = False
            self._wrapper = None
            self._retry_at = time.monotonic() + self._retry_seconds
            LOG.warning("OLA unavailable: %s", exc)
            self._emit(f"[Halo] OLA unavailable; continuing Translation: {exc}")

    def _tick(self):
        if self._closed:
            return
        with self._lock:
            frame = array.array("B", self._frame)
        try:
            self._wrapper.Client().SendDmx(self.universe, frame, self._sent)
            self._wrapper.AddEvent(max(1, round(1000 / self.refresh_hz)), self._tick)
        except Exception as exc:
            LOG.warning("OLA send failed: %s", exc)
            self._emit(f"[Halo] OLA send failed; continuing Translation: {exc}")

    def _blackout_and_stop(self):
        try:
            self._wrapper.Client().SendDmx(self.universe, array.array("B", [0] * 512), lambda _result: self._wrapper.Stop())
        except Exception:
            try: self._wrapper.Stop()
            except Exception: pass

    @staticmethod
    def _sent(result):
        if hasattr(result, "Succeeded") and not result.Succeeded():
            LOG.warning("OLA rejected a DMX frame")
