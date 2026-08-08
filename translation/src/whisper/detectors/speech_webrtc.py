"""WebRTC VAD speech detector for canonical 16 kHz, 30 ms pipeline frames."""

import numpy as np

from ..interfaces import SpeechDetector
from ..models import SpeechDetectionResult


class WebRTCSpeechDetector(SpeechDetector):
    """Wrap WebRTC VAD without changing the pipeline's float32 frame format."""

    VALID_AGGRESSIVENESS = (0, 1, 2, 3)
    FRAME_SAMPLES = 480
    speech_backend = "webrtc"

    def __init__(self, sample_rate=16000, aggressiveness=1, vad=None, vad_factory=None, **_unused_kwargs):
        if sample_rate != 16000:
            raise ValueError("WebRTCSpeechDetector currently requires 16000Hz audio")
        if aggressiveness not in self.VALID_AGGRESSIVENESS:
            raise ValueError("WebRTC aggressiveness must be one of 0, 1, 2, or 3")
        if vad is None:
            if vad_factory is None:
                try:
                    import webrtcvad
                except ImportError as exc:
                    raise RuntimeError(
                        "WebRTC VAD requires webrtcvad-wheels. Install it before selecting "
                        "speech_detector.implementation: webrtc"
                    ) from exc
                vad_factory = webrtcvad.Vad
            vad = vad_factory(aggressiveness)
        self.sample_rate = sample_rate
        self.aggressiveness = aggressiveness
        self.vad = vad

    @staticmethod
    def _pcm16_bytes(frame):
        samples = np.asarray(frame, dtype=np.float32)
        if samples.ndim != 1:
            raise ValueError("WebRTCSpeechDetector expects a mono 1-D NumPy array")
        # WebRTC accepts signed little-endian PCM.  The live/source frame itself
        # remains canonical float32; conversion is deliberately local here.
        return np.rint(np.clip(np.nan_to_num(samples), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

    def classify(self, frame):
        samples = np.asarray(frame, dtype=np.float32)
        if len(samples) != self.FRAME_SAMPLES:
            raise ValueError("WebRTCSpeechDetector requires 480 samples (30 ms at 16000Hz)")
        is_speech = bool(self.vad.is_speech(self._pcm16_bytes(samples), self.sample_rate))
        return SpeechDetectionResult(
            is_speech=is_speech,
            speech_probability=None,
            features={"backend": "webrtc", "evaluated": True, "aggressiveness": self.aggressiveness},
        )
