import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))


import sys
from pathlib import Path
import time
import subprocess
import numpy as np
import collections
import signal
import select

# -----------------------------
# PATH SETUP
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "src"))

# -----------------------------
# CONFIG
# -----------------------------
from configs.whisper import (
    SAMPLE_RATE,
    FRAME_MS,
    DEVICE,
    WHISPER_FRAMES_REQUIRED,
    COOLDOWN_SECONDS,
    RUN_DURATION_SECONDS,
    TRIGGER_RATIO
)

from configs.servos import (
    MIN_PULSE,
    MAX_PULSE,
    HOME_PULSE
)

# -----------------------------
# MODULES
# -----------------------------
from whisper.detector import WhisperDetector
from servo.controller import ServoController
from servo.sweeps import simple_sweep

# -----------------------------
# AUDIO FRAME
# -----------------------------
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)
FRAME_BYTES = FRAME_SIZE * 2


# -----------------------------
# AUDIO PROCESS
# -----------------------------
def start_arecord():
    return subprocess.Popen(
        [
            "arecord",
            "-D", DEVICE,
            "-f", "S16_LE",
            "-r", str(SAMPLE_RATE),
            "-c", "1",
            "-t", "raw"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0
    )


# -----------------------------
# STATE
# -----------------------------
audio_proc = None
servo = None
start_time = None
last_trigger_time = 0
whisper_count = 0


# -----------------------------
# SHUTDOWN (ROBUST)
# -----------------------------
def shutdown(*_):
    global audio_proc, servo

    print("\nShutdown...")

    if audio_proc:
        try:
            audio_proc.terminate()
        except Exception:
            pass

    if servo:
        try:
            servo.shutdown()
        except Exception:
            pass

    raise SystemExit


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


# -----------------------------
# MAIN LOOP
# -----------------------------
def main():
    global audio_proc, servo, start_time, last_trigger_time, whisper_count

    detector = WhisperDetector()
    audio_proc = start_arecord()

    servo = ServoController(
        channel=0,
        frequency=50,
        home_pulse=HOME_PULSE
    )

    servo.go_home()

    start_time = time.time()

    print("Voice rack running...")

    try:
        while True:

            # -----------------------------
            # TIME LIMIT (10 min)
            # -----------------------------
            if time.time() - start_time > RUN_DURATION_SECONDS:
                print("Run time complete")
                break

            # -----------------------------
            # NON-BLOCKING AUDIO READ
            # -----------------------------
            r, _, _ = select.select([audio_proc.stdout], [], [], 1.0)
            if not r:
                continue

            data = audio_proc.stdout.read(FRAME_BYTES)
            if len(data) != FRAME_BYTES:
                continue

            frame = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

            # -----------------------------
            # WHISPER DETECTION (UNCHANGED LOGIC)
            # -----------------------------
            is_whisper, (rms_v, zcr_v, ent_v) = detector.classify(frame)

            if is_whisper:
                whisper_count += 1
            else:
                whisper_count = 0

            now = time.time()
            triggered = False

            if whisper_count >= WHISPER_FRAMES_REQUIRED:
                if now - last_trigger_time > COOLDOWN_SECONDS:
                    triggered = True
                    whisper_count = 0
                    last_trigger_time = now

            # -----------------------------
            # DEBUG OUTPUT (RESTORED FULL)
            # -----------------------------
            print(
                f"WHISPER={is_whisper} "
                f"COUNT={whisper_count} "
                f"RMS={rms_v:.4f} "
                f"ZCR={zcr_v:.3f} "
                f"ENT={ent_v:.2f} "
                f"TRIGGER={triggered}"
            )

            # -----------------------------
            # SERVO ACTION (PRIMITIVES ONLY)
            # -----------------------------
            if triggered:
                print("SERVO: trigger sequence")

                simple_sweep(servo.set_pulse, MIN_PULSE, 1.0)
                simple_sweep(servo.set_pulse, MAX_PULSE, 3.0)
                simple_sweep(servo.set_pulse, MIN_PULSE, 1.3)

    finally:
        shutdown()


if __name__ == "__main__":
    main()
