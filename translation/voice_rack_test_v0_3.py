import subprocess
import numpy as np
import time
import threading

from src.servo import ServoController
from src.servo.sweeps import constant_speed, simple_sweep
from src.whisper import WhisperDetector


# -----------------------------
# Audio config
# -----------------------------
SAMPLE_RATE = 16000
FRAME_MS = 80
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)
FRAME_BYTES = FRAME_SIZE * 2

DEVICE = "plughw:2,0"


# -----------------------------
# Trigger config
# -----------------------------
WHISPER_FRAMES_REQUIRED = 5
COOLDOWN_SECONDS = 5
FRAME_SECONDS = FRAME_MS / 1000.0


# -----------------------------
# state
# -----------------------------
last_trigger_time = 0
whisper_count = 0
servo_busy = False
servo_lock = threading.Lock()


# -----------------------------
# arecord
# -----------------------------
def start_arecord():
    cmd = [
        "arecord",
        "-D", DEVICE,
        "-f", "S16_LE",
        "-r", str(SAMPLE_RATE),
        "-c", "1",
        "-t", "raw"
    ]

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0
    )


# -----------------------------
# servo trigger
# -----------------------------
def trigger_servo(servo):

    global last_trigger_time, servo_busy

    now = time.time()

    if now - last_trigger_time < COOLDOWN_SECONDS:
        return

    if servo_busy:
        return

    last_trigger_time = now

    def run():
        global servo_busy

        with servo_lock:
            servo_busy = True
            try:
                print("\n*** WHISPER TRIGGERED ***\n")

                current = servo.current_pulse

                current = constant_speed(
                    servo_controller=servo,
                    target_pulse=servo.max_pulse,
                    current_pulse=current,
                    speed=800,
                    frame_seconds=FRAME_SECONDS
                )

                time.sleep(0.5)

                current = constant_speed(
                    servo_controller=servo,
                    target_pulse=servo.min_pulse,
                    current_pulse=current,
                    speed=800,
                    frame_seconds=FRAME_SECONDS
                )

                servo.current_pulse = current

                print("*** SWEEP COMPLETE ***\n")

            finally:
                servo_busy = False

    threading.Thread(target=run, daemon=True).start()


# -----------------------------
# main loop
# -----------------------------
def main():

    global whisper_count

    detector = WhisperDetector()
    proc = start_arecord()

    servo = ServoController()

    # -------------------------------------------------
    # STARTUP SAFE POSITION (HOME via simple_sweep)
    # -------------------------------------------------
    servo.current_pulse = simple_sweep(
        servo_controller=servo,
        target_pulse=servo.home_pulse,
        time_allowed=0.5
    )

    print("Listening for whisper detection...")

    try:

        while True:

            data = proc.stdout.read(FRAME_BYTES)
            if len(data) != FRAME_BYTES:
                continue

            frame = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

            is_whisper, (r, z, e) = detector.classify(frame)

            if is_whisper:
                whisper_count += 1
            else:
                whisper_count = 0

            if whisper_count >= WHISPER_FRAMES_REQUIRED:
                whisper_count = 0
                trigger_servo(servo)

            print(
                f"WHISPER={is_whisper} "
                f"COUNT={whisper_count} "
                f"RMS={r:.4f} "
                f"ZCR={z:.3f} "
                f"ENT={e:.2f}"
            )

    except KeyboardInterrupt:
        print("\nCTRL+C detected")

    finally:

        proc.terminate()

        # -------------------------------------------------
        # SAFE SHUTDOWN POSITION (HOME via simple_sweep)
        # -------------------------------------------------
        try:
            simple_sweep(
                servo_controller=servo,
                target_pulse=servo.home_pulse,
                time_allowed=0.5
            )
        except Exception as e:
            print("Home sweep failed:", e)

        try:
            print("Servo shutdown...")
            servo.disable()
            servo.pca.deinit()
        except Exception as e:
            print("Servo shutdown error:", e)

        print("Clean exit")


if __name__ == "__main__":
    main()
