"""Stage 3U bridge from structured ASR results to response presentation."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

from .voice_runtime import VoiceState


class OracleInteractionController:
    """Owns retrieval/display scheduling, never Voice admission or ASR work."""
    def __init__(self, coordinator, retrieval, display, *, emit=print,
                 empty_asr_text=None, retrieval_failure_text=None):
        self.coordinator, self.retrieval, self.display, self.emit = coordinator, retrieval, display, emit
        # Kept only for call compatibility: visitor text belongs to retrieval.
        self._executor, self._future = ThreadPoolExecutor(max_workers=1, thread_name_prefix="oracle-retrieval"), None

    def on_asr_results(self, results):
        for item in results:
            if item.get("status") != "ok":
                self.emit(f"[ASR] ERROR: status={item.get('status')}; using configured fallback response")
                self._submit_fallback("asr_status"); continue
            text = item.get("result", {}).get("recognized_text", "")
            if not isinstance(text, str) or not text.strip():
                self.emit("[ASR] no usable text; [Retrieval] using configured fallback response")
                self._submit_fallback("empty_asr"); continue
            self.emit("[Retrieval] started")
            self._future = self._executor.submit(self.retrieval.retrieve, text)

    def poll(self):
        if self._future and self._future.done():
            future, self._future = self._future, None
            try:
                result = future.result()
                text = result.get("response_text", "") if result.get("ok") else ""
                if not text: raise RuntimeError("empty retrieval response")
                self.emit("[Retrieval] response received")
                self._show_response(text)
            except Exception as exc:
                self.emit(f"[Retrieval] ERROR: {type(exc).__name__}: {exc}")
                self._submit_fallback("retrieval_failure")
        try:
            display_complete = self.display.poll()
        except Exception as exc:
            self.emit(f"[Display] failed: {exc}")
            self.coordinator.complete_interaction("display failure")
            return
        if display_complete and self.coordinator.lifecycle.state is VoiceState.RESPONSE_DISPLAYED:
            self.emit("[Display] response complete")
            self.coordinator.complete_interaction("response display complete")

    def on_voice_transition(self, _previous, state):
        {VoiceState.INITIALIZING: self.display.show_initializing,
         VoiceState.LISTENING: self.display.show_listening,
         VoiceState.WHISPER_DETECTED: self.display.show_whisper_detected,
         VoiceState.CAPTURE_PROCESSING: self.display.show_processing}.get(state, lambda: None)()

    def _submit_fallback(self, reason):
        self.emit("[Retrieval] using configured fallback response")
        self._future = self._executor.submit(self.retrieval.fallback_response, reason)
    def _show_response(self, text):
        self.emit(f"[Response] {text!r}")
        self.coordinator.lifecycle.set(VoiceState.RESPONSE_DISPLAYED)
        try:
            self.display.show_response(text)
        except Exception as exc:
            self.emit(f"[Display] failed: {exc}")
            self.coordinator.complete_interaction("display failure")
    def close(self):
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.display.close()
