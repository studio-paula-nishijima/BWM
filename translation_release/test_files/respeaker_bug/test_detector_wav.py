import time
import numpy as np
import soundfile as sf
import collections

from src.whisper.detector import WhisperDetector

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

WAV_FILE = "test_whisper.wav"

SAMPLE_RATE = 16000
FRAME_MS = 30

FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)

WHISPER_FRAMES_REQUIRED = 10


# --------------------------------------------------
# LOAD WAV
# --------------------------------------------------

audio, sr = sf.read(WAV_FILE)

print(f"File sample rate: {sr}")
print(f"Expected sample rate: {SAMPLE_RATE}")
print(f"Samples: {len(audio)}")

if sr != SAMPLE_RATE:
    raise RuntimeError(
        f"Sample rate mismatch: WAV={sr}, expected={SAMPLE_RATE}"
    )


# Ensure mono
if audio.ndim > 1:
    print("Stereo file detected, using left channel")
    audio = audio[:, 0]


# Ensure float32 like live pipeline
audio = audio.astype(np.float32)


# --------------------------------------------------
# DETECTOR
# --------------------------------------------------

detector = WhisperDetector()

whisper_count = 0


# --------------------------------------------------
# PROCESS FRAMES
# --------------------------------------------------

for i in range(0, len(audio) - FRAME_SIZE, FRAME_SIZE):

    frame = audio[i:i + FRAME_SIZE]


    is_whisper, (rms_v, zcr_v, ent_v) = detector.classify(frame)


    if is_whisper:
        whisper_count += 1
    else:
        whisper_count = 0


    triggered = whisper_count >= WHISPER_FRAMES_REQUIRED


    print(
        f"WHISPER={is_whisper} "
        f"COUNT={whisper_count} "
        f"RMS={rms_v:.4f} "
        f"ZCR={zcr_v:.3f} "
        f"ENT={ent_v:.2f} "
        f"TRIGGER={triggered}"
    )
