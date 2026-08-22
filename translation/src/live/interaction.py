"""Stage 3U bridge from structured ASR results to response presentation."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

from .voice_runtime import VoiceState


class OracleInteractionController:
    """Owns retrieval/display scheduling, never Voice admission or ASR work."""
    def __init__(self, coordinator, retrieval, display, *, emit=print,
                 empty_asr_text="I could not hear a question. Please try again.",
                 retrieval_failure_text="The Oracle cannot answer just now. Please try again."):
        self.coordinator, self.retrieval, self.display, self.emit = coordinator, retrieval, display, emit
        self.empty_asr_text, self.retrieval_failure_text = empty_asr_text, retrieval_failure_text
        self._executor, self._future = ThreadPoolExecutor(max_workers=1, thread_name_prefix="oracle-retrieval"), None

    def on_asr_results(self, results):
        for item in results:
            if item.get("status") != "ok":
                self._show_fallback(self.retrieval_failure_text); continue
            text = item.get("result", {}).get("recognized_text", "")
            if not isinstance(text, str) or not text.strip():
                self.emit("[Retrieval] skipped: no usable ASR text")
                self._show_fallback(self.empty_asr_text); continue
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
                self.emit(f"[Retrieval] failed: {exc}")
                self._show_fallback(self.retrieval_failure_text)
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
        {VoiceState.LISTENING: self.display.show_listening,
         VoiceState.WHISPER_DETECTED: self.display.show_whisper_detected,
         VoiceState.CAPTURE_PROCESSING: self.display.show_processing}.get(state, lambda: None)()

    def _show_fallback(self, text): self._show_response(text)
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
