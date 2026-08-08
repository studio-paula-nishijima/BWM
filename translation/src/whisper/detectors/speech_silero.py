"""Streaming Silero speech detector.

The application supplies 30 ms (480 sample) frames, while Silero's 16 kHz
streaming API consumes 512 samples.  This adapter joins source frames before
calling Silero so that no artificial silence is introduced between frames.
"""

import logging

import numpy as np

from ..interfaces import SpeechDetector
from ..models import SpeechDetectionResult


LOGGER = logging.getLogger(__name__)


class SileroSpeechDetector(SpeechDetector):
    """Adapt 480-sample pipeline frames to continuous 512-sample windows."""

    WINDOW_SAMPLES = 512
    provides_silero_probability = True

    def __init__(
        self,
        sample_rate=16000,
        threshold=0.5,
        model=None,
        model_loader=None,
        **_unused_kwargs,
    ):
        if sample_rate != 16000:
            raise ValueError("SileroSpeechDetector currently requires 16000Hz audio")

        self.sample_rate = sample_rate
        self.threshold = threshold
        self._torch = None
        self.model = model if model is not None else self._load_model(model_loader)
        self.reset()

    def _load_model(self, model_loader):
        """Load one backend once; dependency injection keeps tests/network out of startup."""
        if model_loader is not None:
            return model_loader()

        try:
            import torch
        except ImportError as exc:
            raise RuntimeError(
                "Silero requires PyTorch. Install it before selecting "
                "speech_detector.implementation: silero"
            ) from exc

        torch.set_num_threads(1)
        self._torch = torch
        model, _utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
        )
        return model

    def reset(self):
        """Start a fresh audio stream and clear Silero's recurrent state."""
        self._samples = np.empty(0, dtype=np.float32)
        self._latest_probability = None
        if hasattr(self.model, "reset_states"):
            self.model.reset_states()

    def _infer(self, samples):
        if self._torch is None:
            # Test/injected backends may intentionally accept raw NumPy arrays.
            output = self.model(samples, self.sample_rate)
        else:
            tensor = self._torch.from_numpy(samples)
            with self._torch.no_grad():
                output = self.model(tensor, self.sample_rate)

        if hasattr(output, "item"):
            return float(output.item())
        return float(output)

    def classify(self, frame):
        """Classify all complete continuous Silero windows now available.

        A call can process multiple windows if a future caller supplies a frame
        larger than 512 samples.  The result represents the newest inference;
        before the first complete window it explicitly reports a pending result.
        """
        samples = np.asarray(frame, dtype=np.float32)
        if samples.ndim != 1:
            raise ValueError("SileroSpeechDetector expects a mono 1-D NumPy array")

        self._samples = np.concatenate((self._samples, samples))
        windows_processed = len(self._samples) // self.WINDOW_SAMPLES

        for window_number in range(windows_processed):
            start = window_number * self.WINDOW_SAMPLES
            end = start + self.WINDOW_SAMPLES
            window = self._samples[start:end]
            self._latest_probability = self._infer(window)

        if windows_processed:
            # Keep precisely the incomplete continuous tail for the next call.
            # Copying releases the consumed prefix instead of retaining the full
            # previous input array through a NumPy view.
            self._samples = self._samples[
                windows_processed * self.WINDOW_SAMPLES:
            ].copy()

        pending = self._latest_probability is None
        probability = 0.0 if pending else self._latest_probability
        features = {
            "pending": pending,
            "buffered_samples": len(self._samples),
            "inference_ran": windows_processed > 0,
            "windows_processed": windows_processed,
        }
        LOGGER.debug("Silero frame: %s", features)

        return SpeechDetectionResult(
            is_speech=(not pending and probability >= self.threshold),
            speech_probability=probability,
            features=features,
        )
