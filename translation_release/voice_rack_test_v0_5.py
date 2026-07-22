import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))


from pathlib import Path
import time
import subprocess
import numpy as np
import collections
import signal
import select
import random

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
from servo.sweeps import simple_sweep, constant_speed

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
                sequence_number = random.randint(1,5)
                
                print(f"SERVO: trigger sequence:{sequence_number}")
                
                if sequence_number == 1:
                    simple_sweep(servo.set_pulse, MIN_PULSE, 0.5)
                    simple_sweep(servo.set_pulse, MAX_PULSE, 3.0)
                    simple_sweep(servo.set_pulse, MIN_PULSE, 1.5)
                
                elif sequence_number == 2:
                    simple_sweep(servo.set_pulse, MIN_PULSE, 0.3)
                    simple_sweep(servo.set_pulse, MAX_PULSE, 1.5)
                    simple_sweep(servo.set_pulse, MIN_PULSE, 1.5)
                    simple_sweep(servo.set_pulse, MIN_PULSE, 2.0)
                    simple_sweep(servo.set_pulse, MIN_PULSE, 1.5)
                
                elif sequence_number == 3:
                    simple_sweep(servo.set_pulse, MIN_PULSE, 0.3)
                    constant_speed(servo.set_pulse, MIN_PULSE, MAX_PULSE, 800)
                    time.sleep(1)
                    constant_speed(servo.set_pulse, MAX_PULSE, MIN_PULSE, 500)
                
                elif sequence_number == 4:
                    simple_sweep(servo.set_pulse, MIN_PULSE, 0.3)
                    simple_sweep(servo.set_pulse, MAX_PULSE, 1.5)
                    simple_sweep(servo.set_pulse, MIN_PULSE, 1.8)
                    constant_speed(servo.set_pulse, MIN_PULSE, MAX_PULSE, 1200)
                    time.sleep(0.2)
                    constant_speed(servo.set_pulse, MAX_PULSE, MIN_PULSE, 1000)
                
                elif sequence_number == 5:
                    simple_sweep(servo.set_pulse, MIN_PULSE, 0.3)
                    constant_speed(servo.set_pulse, MIN_PULSE, MAX_PULSE, 500)
                    simple_sweep(servo.set_pulse, MIN_PULSE, 1.5)
                    
                
                else:
                    print("random error")
                

               

    finally:
        shutdown()


if __name__ == "__main__":
    main()
