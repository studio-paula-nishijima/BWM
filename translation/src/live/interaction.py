"""Stage 3U bridge from structured ASR results to response presentation."""
from __future__ import annotations

from .voice_runtime import VoiceState


def compact_preview(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= 100 else f"{text[:50]} ... {text[-50:]}"


def retrieval_debug_line(result: dict) -> str | None:
    """Compact, provenance-preserving diagnostic for the returned top chunk."""
    raw = result.get("metadata", {}).get("raw_results", [])
    if not raw:
        return None
    chunk = raw[0]
    preview = compact_preview(chunk.get("text", ""))
    printed, pdf = chunk.get("printed_pages") or [], chunk.get("pdf_pages") or []
    def pages(label, values):
        values = [str(value) for value in values]
        if len(values) == 1: return f"{label} page {values[0]}"
        if len(values) == 2: return f"{label} pages {values[0]}–{values[1]}"
        return f"{label} pages {', '.join(values)}"
    provenance = pages("book", printed) if printed else pages("PDF", pdf) if pdf else ""
    prefix = f"[Retrieval] {provenance} | " if provenance else "[Retrieval] "
    return f'{prefix}chunk: "{preview}"'


class OracleInteractionController:
    """Owns retrieval/display scheduling, never Voice admission or ASR work."""
    def __init__(self, coordinator, retrieval, display, *, emit=print,
                 empty_asr_text=None, retrieval_failure_text=None):
        self.coordinator, self.retrieval, self.display, self.emit = coordinator, retrieval, display, emit
        # Kept only for call compatibility: visitor text belongs to retrieval.
        self._job_id = None

    def on_asr_results(self, results):
        for item in results:
            if item.get("status") == "timeout":
                self.emit("[Retrieval] using configured fallback response")
                self._show_fallback("asr_timeout"); continue
            if item.get("status") != "ok":
                self.emit(f"[ASR] ERROR: status={item.get('status')}; using configured fallback response")
                self._show_fallback("asr_status"); continue
            text = item.get("result", {}).get("recognized_text", "")
            if not isinstance(text, str) or not text.strip():
                self.emit("[ASR] no usable text; [Retrieval] using configured fallback response")
                self._show_fallback("empty_asr"); continue
            self._job_id, status = self.retrieval.submit(text)
            self.emit("[Retrieval] submitted" if status == "accepted" else f"[RetrievalWorker] error: {status}")
            if status != "accepted": self._show_fallback(status)

    def poll(self):
        for item in self.retrieval.poll():
            try:
                if not item["ok"]: raise RuntimeError(item["error"])
                result = item["result"]
                text = result.get("response_text", "") if result.get("ok") else ""
                if not text: raise RuntimeError("empty retrieval response")
                self.emit("[Retrieval] response received")
                debug_line = retrieval_debug_line(result)
                if debug_line:
                    self.emit(debug_line)
                self._show_response(text)
            except Exception as exc:
                self.emit(f"[Retrieval] ERROR: {type(exc).__name__}: {exc}")
                self._show_fallback("retrieval_failure")
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

    def _show_fallback(self, reason):
        self.emit("[Retrieval] using configured fallback response")
        submit = getattr(self.retrieval, "submit_fallback", None)
        if submit and submit(reason)[1] == "accepted": return
        self._show_response(self.retrieval.fallback_response(reason)["response_text"])
    def _show_response(self, text):
        self.emit(f'[Response] "{compact_preview(text)}"')
        self.coordinator.lifecycle.set(VoiceState.RESPONSE_DISPLAYED)
        try:
            self.display.show_response(text)
        except Exception as exc:
            self.emit(f"[Display] failed: {exc}")
            self.coordinator.complete_interaction("display failure")
    def close(self):
        self.retrieval.shutdown()
        self.display.close()
