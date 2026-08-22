"""Transport-independent live trigger, capture, ASR and Voice-state bridge."""
from __future__ import annotations

import time
from enum import Enum

from analysis.asr_evaluation import AudioSegment


class VoiceState(str, Enum):
    IDLE = "idle"
    INITIALIZING = "initializing"
    LISTENING = "listening"
    WHISPER_DETECTED = "whisper_detected"
    CAPTURE_PROCESSING = "capture_processing"
    RESPONSE_DISPLAYED = "response_displayed"


class VoiceLifecycle:
    """Small authoritative state boundary with an optional transition observer.

    The observer is an integration seam.  It cannot alter a transition and is
    deliberately kept outside capture, detector and ASR concerns.
    """
    def __init__(self, emit=print, on_transition=None):
        self.state = VoiceState.IDLE
        self._emit = emit
        self._on_transition = on_transition

    def add_transition_observer(self, observer):
        previous = self._on_transition
        if previous is None:
            self._on_transition = observer
        else:
            self._on_transition = lambda before, after: (previous(before, after), observer(before, after))

    def set(self, state):
        state = VoiceState(state)
        if state == self.state:
            return False
        previous, self.state = self.state, state
        self._emit(f"[Voice] state: {previous.value} -> {state.value}")
        if self._on_transition:
            try:
                self._on_transition(previous, state)
            except Exception as exc:
                # External observability must never invalidate local admission.
                self._emit(f"[Voice] transition observer failed: {exc}")
        return True


class LiveASRCoordinator:
    """Feed canonical frames without ever waiting for model inference."""
    def __init__(self, capture, worker=None, *, lifecycle=None, emit=print,
                 source_id="live", detector_profile="", output_mode="transcribe", language=None,
                 release_after_asr=False, startup_ready=None):
        self.capture = capture
        self.worker = worker
        self.lifecycle = lifecycle or VoiceLifecycle(emit)
        self.emit = emit
        self.source_id, self.detector_profile = source_id, detector_profile
        self.output_mode, self.language = output_mode, language
        self._submitted = {}
        self.results = []
        self._asr_status = None
        self._startup_failure_reported = False
        self.release_after_asr = release_after_asr
        self.startup_ready = startup_ready or (lambda: (True, ""))

    @property
    def accepting_interaction(self):
        return self.lifecycle.state is VoiceState.LISTENING and not self.capture.is_capturing

    def start(self):
        self.lifecycle.set(VoiceState.INITIALIZING)
        if self.worker:
            self.emit("[ASR] loading")
            self._asr_status = "loading"
            self.worker.start()
        else:
            self.emit("[Voice] ASR disabled; initialization complete")
            self.lifecycle.set(VoiceState.LISTENING)

    def ready_status(self):
        if not self.worker:
            status, message = "disabled", "[ASR] disabled"
        elif self.worker.ready:
            status, message = "ready", "[ASR] ready"
        elif self.worker.startup_error:
            status, message = "unavailable", f"[ASR] unavailable: {self.worker.startup_error}"
        else:
            status, message = "loading", "[ASR] loading"
        if status != self._asr_status:
            self._asr_status = status
            self.emit(message)
        dependencies_ready, dependency_error = self.startup_ready()
        if status == "ready" and dependencies_ready and self.lifecycle.state is VoiceState.INITIALIZING:
            self.emit("[Voice] required startup resources ready")
            self.lifecycle.set(VoiceState.LISTENING)
        elif status == "unavailable" and self.lifecycle.state is VoiceState.INITIALIZING:
            if not self._startup_failure_reported:
                self._startup_failure_reported = True
                self.emit(f"[Voice] initialization failed: {self.worker.startup_error}; Voice remains unavailable")
        elif dependency_error:
            self.emit(f"[RetrievalWorker] error: {dependency_error}")
        return status

    def process_frame(self, frame, frame_number, *, emitted_trigger, temporal_candidate):
        # Readiness is checked before admission, so the first trigger after the
        # persistent worker reports ready is eligible without faking startup.
        if self.lifecycle.state is VoiceState.INITIALIZING:
            self.ready_status()
        admitted_trigger = False
        if emitted_trigger:
            self.emit("[Trigger] whisper detected")
            if self.accepting_interaction:
                admitted_trigger = True
                self.lifecycle.set(VoiceState.WHISPER_DETECTED)
            else:
                self.emit(f"[Interaction] ignored: busy ({self.lifecycle.state.value})")
        completed = self.capture.process_frame(frame, frame_number, admitted_trigger, temporal_candidate)
        if self.capture.is_capturing and admitted_trigger:
            self.emit("[Capture] started")
        if completed:
            self._submit(completed)
        return self.poll()

    def complete_interaction(self, reason="external"):
        """Release admission after a future response/display stage has finished.

        Stage 3T deliberately never calls this during ordinary ASR completion:
        ASR is only one part of the eventual interaction lifecycle.
        """
        if self.capture.is_capturing or self.lifecycle.state not in (VoiceState.CAPTURE_PROCESSING, VoiceState.RESPONSE_DISPLAYED):
            return False
        self.emit(f"[Interaction] complete: {reason}")
        return self.lifecycle.set(VoiceState.LISTENING)

    def finish_capture(self):
        completed = self.capture.finish()
        if completed:
            self._submit(completed)
        return self.poll()

    def _submit(self, capture):
        duration = len(capture.samples) / float(capture.sample_rate)
        self.emit(f"[Capture] complete: {duration:.1f} s ({capture.completion_reason})")
        self.lifecycle.set(VoiceState.CAPTURE_PROCESSING)
        capture_id = f"{capture.source_id}:{capture.capture_index}"
        submitted = time.monotonic()
        metadata = {"capture_id": capture_id, "source_id": capture.source_id,
                    "detector_profile": capture.detector_profile,
                    "trigger_time_seconds": capture.time(capture.trigger_sample),
                    "capture_completion_monotonic": submitted,
                    "asr_output_mode": self.output_mode, "language": self.language,
                    "language_mode": "auto" if self.language is None else "supplied",
                    # Keep identity/timing without serialising the audio twice;
                    # the AudioSegment below is the sole audio payload.
                    "capture": {"capture_index": capture.capture_index,
                                "trigger_frame": capture.trigger_frame,
                                "trigger_sample": capture.trigger_sample,
                                "capture_start_sample": capture.capture_start_sample,
                                "final_end_sample": capture.final_end_sample,
                                "completion_reason": capture.completion_reason}}
        if not self.worker:
            self.emit("[ASR] disabled")
            return
        job_id, status = self.worker.submit(AudioSegment(capture.samples, capture.sample_rate, capture.source_id), metadata)
        if status != "accepted":
            self.emit(f"[ASR] busy: {status} ({capture_id})")
            self.results.append({"capture_id": capture_id, "status": status, "error": status, "metadata": metadata})
            return
        self._submitted[job_id] = submitted
        self.emit(f"[ASR] job submitted: {capture_id}")
        self.emit("[ASR] processing")

    def poll(self):
        if not self.worker:
            return []
        completed = []
        for item in self.worker.poll():
            finished = time.monotonic()
            metadata = item["metadata"]
            submitted = self._submitted.pop(item["job_id"], metadata.get("capture_completion_monotonic", finished))
            item.update({"capture_id": metadata.get("capture_id"), "source_id": metadata.get("source_id"),
                         "detector_profile": metadata.get("detector_profile"),
                         "asr_submitted_monotonic": submitted, "asr_completed_monotonic": finished,
                         "queue_delay": max(0.0, item.get("worker_started_monotonic", submitted) - submitted),
                         "real_time_factor": item["inference_duration"] / item["audio_duration"] if item["audio_duration"] else None,
                         "asr_backend": self.worker.config.backend, "asr_model": self.worker.config.model,
                         "compute_type": self.worker.config.compute_type, "cpu_threads": self.worker.config.cpu_threads})
            if item["status"] == "ok":
                result = item["result"]
                if result.get("detected_language"):
                    self.emit(f"[ASR] language={result['detected_language']}")
                rtf = item["real_time_factor"]
                suffix = f"; RTF={rtf:.2f}" if rtf is not None else ""
                self.emit(f"[ASR] complete: {item['inference_duration']:.2f} s{suffix}")
                self.emit(f"[ASR] {result.get('recognized_text', '')!r}")
            else:
                self.emit(f"[ASR] error after {item['inference_duration']:.2f} s: {item['error']}")
            self.results.append(item); completed.append(item)
            if self.release_after_asr:
                self.complete_interaction("debug ASR completion")
        return completed

    def shutdown(self):
        if self.worker:
            self.worker.shutdown()
        self.lifecycle.set(VoiceState.IDLE)
