"""Persistent OLA CLI source; application code never owns a serial DMX device."""
from __future__ import annotations

import logging
import subprocess
import threading

LOG = logging.getLogger(__name__)


class OLAUniverseClient:
    """Feed successive DMX frames to one long-lived ``ola_streaming_client``."""

    def __init__(self, universe, *, refresh_hz=30, retry_seconds=5,
                 executable="ola_streaming_client", popen_factory=subprocess.Popen,
                 run_factory=subprocess.run, blackout_timeout_seconds=1.0,
                 emit=print):
        self.universe = int(universe)
        self.refresh_hz = float(refresh_hz)
        if self.refresh_hz <= 0:
            raise ValueError("OLA refresh rate must be positive")
        self._retry_seconds = float(retry_seconds)
        self._executable = executable
        self._popen_factory = popen_factory
        self._run_factory = run_factory
        self._blackout_timeout_seconds = float(blackout_timeout_seconds)
        self._emit = emit
        self._frame = bytearray()
        self._frame_lock = threading.Lock()
        self._thread_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._process = None
        self._thread = None
        self._stop = threading.Event()
        self._closed = False

    def send(self, frame):
        if not 1 <= len(frame) <= 512:
            raise ValueError("OLA universe frames must contain 1 to 512 channels")
        if self._closed:
            return
        with self._frame_lock:
            self._frame[:] = frame
        with self._thread_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="ola-halo", daemon=True)
                self._thread.start()

    def close(self):
        if self._closed:
            return
        self._closed = True
        with self._frame_lock:
            blackout = bytes(len(self._frame))
            self._frame[:] = blackout
        # Stop the refresh loop before the final write so no older frame can be
        # emitted after blackout.
        self._stop.set()
        process = self._process
        if process is not None and process.poll() is None:
            try:
                with self._write_lock:
                    process.stdin.write(self._payload(blackout))
                    process.stdin.flush()
                    process.stdin.close()
            except Exception:
                pass
        self._close_process(process)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.5)
        if blackout:
            self._latch_blackout(blackout)

    def _run(self):
        while not self._stop.is_set():
            process = None
            try:
                process = self._popen_factory(
                    [self._executable, "-u", str(self.universe)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    bufsize=0,
                )
                self._process = process
                while not self._stop.is_set():
                    if process.poll() is not None:
                        raise OSError("ola_streaming_client exited")
                    with self._frame_lock:
                        frame = bytes(self._frame)
                    self._write(process, frame)
                    self._stop.wait(1.0 / self.refresh_hz)
            except Exception as exc:
                if not self._stop.is_set():
                    LOG.warning("OLA unavailable: %s", exc)
                    self._emit(f"[Halo] OLA unavailable; continuing Translation: {exc}")
            finally:
                self._close_process(process)
                if self._process is process:
                    self._process = None
            if not self._stop.is_set():
                self._stop.wait(self._retry_seconds)

    def _write(self, process, frame):
        # Without -d, the packaged client accepts successive comma-separated
        # frames on stdin and remains one OLA source for its process lifetime.
        with self._write_lock:
            process.stdin.write(self._payload(frame))
            process.stdin.flush()

    def _latch_blackout(self, blackout):
        """Best-effort final state using the one-shot path proven on rpi05."""
        try:
            result = self._run_factory(
                [self._executable, "-u", str(self.universe), "-d", self._dmx_arg(blackout)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                timeout=self._blackout_timeout_seconds,
                check=False,
            )
            if getattr(result, "returncode", 0):
                LOG.warning("OLA one-shot blackout exited with status %s", result.returncode)
        except Exception as exc:
            LOG.warning("OLA one-shot blackout failed: %s", exc)
            self._emit(f"[Halo] OLA blackout failed; continuing shutdown: {exc}")

    @staticmethod
    def _payload(frame):
        return (OLAUniverseClient._dmx_arg(frame) + "\n").encode("ascii")

    @staticmethod
    def _dmx_arg(frame):
        return ",".join(str(value) for value in frame)

    @staticmethod
    def _close_process(process):
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except Exception:
            pass
        try:
            if process.poll() is None:
                # EOF lets ola_streaming_client consume the final blackout,
                # submit it to olad, and withdraw normally.  Terminating first
                # can kill it before that last stdin frame is processed.
                process.wait(timeout=0.5)
                return
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=0.25)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
