from .source import AudioSource, AudioFrame
from .arecord_source import ArecordSource
from .ring_buffer import AudioRingBuffer
from .utterance_capture import CapturePolicy, CaptureState, CompletedCapture, UtteranceCaptureController

# Ring-buffer and capture-state tests do not need libsndfile.  Keep the normal
# WavSource export when the optional offline WAV dependency is installed.
try:
    from .wav_source import WavSource
except ModuleNotFoundError as exc:
    if exc.name != "soundfile":
        raise
