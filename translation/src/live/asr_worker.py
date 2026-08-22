"""Bounded, persistent, lower-priority process for completed capture ASR."""
from __future__ import annotations

import multiprocessing as mp
import os
import queue
import signal
import time
from dataclasses import asdict, dataclass
from typing import Callable

from analysis.asr_evaluation import ASRResult, AudioSegment, FasterWhisperBackend


@dataclass(frozen=True)
class ASRWorkerConfig:
    backend: str = "faster_whisper"
    model: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"
    cpu_threads: int = 2
    worker_nice: int = 10
    queue_size: int = 1

    def validate(self):
        if self.backend != "faster_whisper": raise ValueError("Only faster_whisper is currently supported")
        if self.device != "cpu": raise ValueError("The live fallback worker is CPU-only")
        if self.cpu_threads < 1: raise ValueError("cpu_threads must be at least 1")
        if self.queue_size < 1: raise ValueError("queue_size must be at least 1")


def _default_backend(config):
    return FasterWhisperBackend(config.model, config.device, config.compute_type, config.cpu_threads)


def _reset_worker_signal_handlers():
    """Keep the forked ASR child out of the application's shutdown path.

    On Linux ``fork`` copies the live runner's SIGINT/SIGTERM handlers.  Those
    handlers own parent-only resources (notably ``Process.join``), so they
    must not run in this child when it is stopped by the parent.
    """
    if os.name == "posix":
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)


def _worker_main(config, requests, results, ready_event, startup_errors, backend_factory):
    _reset_worker_signal_handlers()
    try:
        if os.name == "posix" and config.worker_nice:
            os.nice(config.worker_nice)
        backend = (backend_factory or _default_backend)(config)
        # Force a single model load at worker start, rather than the first job.
        if hasattr(backend, "_load"): backend._load()
        ready_event.set()
    except Exception as exc:
        startup_errors.put(f"{type(exc).__name__}: {exc}"); return
    while True:
        job = requests.get()
        if job is None: return
        job_id, audio, metadata = job
        started = time.monotonic()
        try:
            result = backend.transcribe(audio, output_mode=metadata.get("asr_output_mode", "transcribe"), language=metadata.get("language"))
            payload, status, error = asdict(result), "ok", ""
        except Exception as exc:
            payload, status, error = asdict(ASRResult()), "inference_failed", f"{type(exc).__name__}: {exc}"
        results.put({"job_id": job_id, "status": status, "error": error, "result": payload,
                     "metadata": metadata, "audio_duration": audio.duration_seconds,
                     "worker_started_monotonic": started,
                     "inference_duration": time.monotonic() - started})


class PersistentASRWorker:
    """One active ASR process and at most ``queue_size`` pending capture jobs."""
    def __init__(self, config=ASRWorkerConfig(), *, backend_factory: Callable | None = None, context=None):
        config.validate(); self.config = config; self._context = context or mp.get_context()
        self._requests, self._results = self._context.Queue(config.queue_size), self._context.Queue()
        self._ready, self._startup_errors = self._context.Event(), self._context.Queue(1)
        self._startup_error, self._process, self._factory, self._next_id = None, None, backend_factory, 1

    def start(self):
        if self._process and self._process.is_alive(): return
        self._process = self._context.Process(target=_worker_main, args=(self.config, self._requests, self._results, self._ready, self._startup_errors, self._factory), daemon=True)
        self._process.start()

    @property
    def ready(self): return self._ready.is_set()
    @property
    def startup_error(self):
        if self._startup_error is None:
            try: self._startup_error = self._startup_errors.get_nowait()
            except queue.Empty: pass
        return self._startup_error

    def submit(self, audio: AudioSegment, metadata=None):
        if not self._process or not self._process.is_alive(): return None, "worker_unavailable"
        job_id = str(self._next_id); self._next_id += 1
        try: self._requests.put_nowait((job_id, audio, dict(metadata or {})))
        except queue.Full: return None, "queue_full"
        return job_id, "accepted"

    def poll(self):
        items = []
        while True:
            try: items.append(self._results.get_nowait())
            except queue.Empty: return items

    def shutdown(self, timeout=5):
        if self._process:
            try: self._requests.put_nowait(None)
            except queue.Full: pass
            self._process.join(timeout)
            if self._process.is_alive(): self._process.terminate(); self._process.join()
