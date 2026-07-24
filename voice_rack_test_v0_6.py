import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from pathlib import Path
import time
import subprocess
import numpy as np
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
)


# -----------------------------
# MODULES
# -----------------------------
from whisper.detector import WhisperDetector


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
start_time = None
last_trigger_time = 0
whisper_count = 0


# -----------------------------
# SHUTDOWN
# -----------------------------
def shutdown(*_):
    global audio_proc

    print("\nShutdown...")

    if audio_proc:
        try:
            audio_proc.terminate()
        except Exception:
            pass

    raise SystemExit


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


# -----------------------------
# MAIN LOOP
# -----------------------------
def main():
    global audio_proc, start_time
    global last_trigger_time, whisper_count

    detector = WhisperDetector()

    audio_proc = start_arecord()

    start_time = time.time()

    print("Whisper detection running...")
    print("No servo control enabled")

    try:
        while True:

            # -----------------------------
            # TIME LIMIT
            # -----------------------------
            if time.time() - start_time > RUN_DURATION_SECONDS:
                print("Run time complete")
                break


            # -----------------------------
            # AUDIO READ
            # -----------------------------
            r, _, _ = select.select(
                [audio_proc.stdout],
                [],
                [],
                1.0
            )

            if not r:
                continue


            data = audio_proc.stdout.read(FRAME_BYTES)

            if len(data) != FRAME_BYTES:
                continue


            frame = (
                np.frombuffer(data, dtype=np.int16)
                .astype(np.float32)
                / 32768.0
            )


            # -----------------------------
            # WHISPER DETECTION
            # -----------------------------
            is_whisper, (rms_v, zcr_v, ent_v) = detector.classify(frame)


            if is_whisper:
                whisper_count += 1
            else:
                whisper_count = 0


            triggered = False
            now = time.time()


            if whisper_count >= WHISPER_FRAMES_REQUIRED:

                if now - last_trigger_time > COOLDOWN_SECONDS:
                    triggered = True
                    last_trigger_time = now
                    whisper_count = 0


            # -----------------------------
            # DEBUG OUTPUT
            # -----------------------------
            print(
                f"WHISPER={is_whisper} "
                f"COUNT={whisper_count} "
                f"RMS={rms_v:.4f} "
                f"ZCR={zcr_v:.3f} "
                f"ENT={ent_v:.2f} "
                f"TRIGGER={triggered}"
            )


    finally:
        shutdown()


if __name__ == "__main__":
    main()
