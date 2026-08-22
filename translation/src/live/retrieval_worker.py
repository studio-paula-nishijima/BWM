"""Persistent process boundary for River Culture retrieval inference."""
from __future__ import annotations

import multiprocessing as mp
import queue
import time
import json
from pathlib import Path


def _worker_main(repository_root, requests, results, ready, errors):
    try:
        # This is intentionally the child process's first heavy retrieval import.
        from .retrieval_adapter import RiverCultureRetrievalAdapter
        adapter = RiverCultureRetrievalAdapter(Path(repository_root))
        adapter.prepare()
        ready.set()
    except Exception as exc:
        errors.put(f"{type(exc).__name__}: {exc}"); return
    while True:
        job = requests.get()
        if job is None: return
        job_id, action, text = job
        try:
            result = adapter.fallback_response(text) if action == "fallback" else adapter.retrieve(text)
            results.put({"job_id": job_id, "ok": True, "result": result})
        except Exception as exc:
            results.put({"job_id": job_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PersistentRetrievalWorker:
    """One warm, bounded retrieval process; it owns all ML initialization."""
    def __init__(self, repository_root, *, context=None):
        self.repository_root, self._context = str(repository_root), context or mp.get_context()
        self._requests, self._results = self._context.Queue(1), self._context.Queue()
        self._ready, self._errors = self._context.Event(), self._context.Queue(1)
        self._process, self._error, self._next_id = None, None, 1
        config = Path(repository_root) / "translation/configs/river_culture_retrieval.json"
        self._fallback = json.loads(config.read_text(encoding="utf-8")).get("fallback_response", {})
    def fallback_response(self, reason):
        text = self._fallback.get("text", "")
        if not text.strip(): raise RuntimeError(f"configured fallback response unavailable ({reason})")
        return {"ok": True, "response_text": text, "metadata": {"fallback": True, "reason": reason}}
    def start(self):
        if self._process and self._process.is_alive(): return
        self._process = self._context.Process(target=_worker_main,
            args=(self.repository_root, self._requests, self._results, self._ready, self._errors), daemon=True)
        self._process.start()
    @property
    def ready(self): return self._ready.is_set()
    @property
    def startup_error(self):
        if self._error is None:
            try: self._error = self._errors.get_nowait()
            except queue.Empty: pass
        if self._process and not self._process.is_alive() and self._error is None:
            self._error = "worker exited before ready"
        return self._error
    def submit(self, text):
        if not self.ready or not self._process or not self._process.is_alive(): return None, "worker_unavailable"
        job_id = str(self._next_id); self._next_id += 1
        try: self._requests.put_nowait((job_id, "query", text))
        except queue.Full: return None, "queue_full"
        return job_id, "accepted"
    def submit_fallback(self, reason):
        if not self.ready or not self._process or not self._process.is_alive(): return None, "worker_unavailable"
        job_id = str(self._next_id); self._next_id += 1
        try: self._requests.put_nowait((job_id, "fallback", reason))
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
