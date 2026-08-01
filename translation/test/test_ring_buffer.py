import numpy as np
import sys
import os

# -----------------------------
# PATH SETUP
# -----------------------------
BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PROJECT_ROOT = os.path.dirname(BASE_DIR)

sys.path.insert(
    0,
    PROJECT_ROOT
)

from src.audio.ring_buffer import AudioRingBuffer


buffer = AudioRingBuffer(
    sample_rate=16000,
    buffer_seconds=2
)


# simulate 3 seconds audio

for i in range(30):

    frame = np.ones(
        1600,
        dtype=np.float32
    )

    buffer.append(frame)


print(
    "Stored seconds:",
    buffer.duration()
)


recent = buffer.get_recent(1)


print(
    "Recent samples:",
    len(recent)
)


buffer.clear()


print(
    "After clear:",
    buffer.duration()
)
