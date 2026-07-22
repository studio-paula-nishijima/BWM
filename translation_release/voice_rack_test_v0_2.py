import subprocess
import numpy as np
from scipy.signal import butter, lfilter
import collections
import threading
import time

# -----------------------------
# Audio config
# -----------------------------
SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)
BYTES_PER_SAMPLE = 2
FRAME_BYTES = FRAME_SIZE * BYTES_PER_SAMPLE

DEVICE = "plughw:2,0"

# -----------------------------
# Trigger settings
# -----------------------------
WHISPER_FRAMES_REQUIRED = 10
COOLDOWN_SECONDS = 5

last_trigger_time = 0
whisper_count = 0

# -----------------------------
# Servo sweep
# -----------------------------
def run_servo_sweep():

    import board
    import busio
    from adafruit_pca9685 import PCA9685

    # --------------------------------------------
    # Servo settings
    # --------------------------------------------

    minimum_pulse = 800
    maximum_pulse = 2200

    sweeps = 2

    forward_sweep_time = 3
    backward_sweep_time = 1.3

    set_time = 2

    # --------------------------------------------

    i2c = busio.I2C(board.SCL, board.SDA)

    pca = PCA9685(i2c)
    pca.frequency = 50

    servo = pca.channels[0]

    def set_pulse(us):
        duty = int(us / 20000 * 65535)
        servo.duty_cycle = duty

    try:

        print("\nSERVO: move to back")

        set_pulse(minimum_pulse)
        time.sleep(set_time)

        for sweep in range(sweeps):

            print(f"SERVO: sweep {sweep + 1}/{sweeps}")

            set_pulse(maximum_pulse)
            time.sleep(forward_sweep_time)

            set_pulse(minimum_pulse)
            time.sleep(backward_sweep_time)

        print("SERVO: return to back")

        set_pulse(minimum_pulse)
        time.sleep(set_time)

    finally:

        servo.duty_cycle = 0
        pca.deinit()

        print("SERVO: finished")

# -----------------------------
# Trigger helper
# -----------------------------
def trigger_servo():

    global last_trigger_time

    now = time.time()

    if now - last_trigger_time < COOLDOWN_SECONDS:
        return

    last_trigger_time = now

    print("\n*** WHISPER TRIGGERED ***\n")

    threading.Thread(
        target=run_servo_sweep,
        daemon=True
    ).start()

# -----------------------------
# Band-pass filter
# -----------------------------
def bandpass_filter(signal, low=300, high=4000, fs=16000, order=4):
    nyq = 0.5 * fs
    b, a = butter(order, [low / nyq, high / nyq], btype="band")
    return lfilter(b, a, signal)

# -----------------------------
# Features
# -----------------------------
def rms(signal):
    return np.sqrt(np.mean(signal ** 2) + 1e-9)

def zcr(signal):
    return np.mean(np.abs(np.diff(np.sign(signal)))) / 2

def spectral_entropy(signal, eps=1e-9):
    fft = np.fft.rfft(signal)
    psd = np.abs(fft) ** 2
    psd = psd / (np.sum(psd) + eps)
    entropy = -np.sum(psd * np.log(psd + eps))
    return entropy

# -----------------------------
# Whisper detector
# -----------------------------
class WhisperDetector:

    def __init__(self):

        self.history = collections.deque(maxlen=10)

        self.rms_min = 0.005
        self.rms_max = 0.1

        self.zcr_min = 0.05
        self.zcr_max = 0.3

        self.entropy_min = 4.5

    def classify(self, frame):

        frame = bandpass_filter(frame)

        r = rms(frame)
        z = zcr(frame)
        e = spectral_entropy(frame)

        score = 0

        if self.rms_min < r < self.rms_max:
            score += 1

        if self.zcr_min < z < self.zcr_max:
            score += 1

        if e > self.entropy_min:
            score += 1

        is_whisper = score >= 2

        self.history.append(is_whisper)

        stability = sum(self.history) / len(self.history)

        return stability > 0.6, (r, z, e)

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
# Main loop
# -----------------------------
def main():

    global whisper_count

    detector = WhisperDetector()
    proc = start_arecord()

    print("Listening for whispering (arecord)...")

    try:

        while True:

            data = proc.stdout.read(FRAME_BYTES)

            if len(data) != FRAME_BYTES:
                continue

            frame = (
                np.frombuffer(data, dtype=np.int16)
                .astype(np.float32)
                / 32768.0
            )

            is_whisper, (r, z, e) = detector.classify(frame)

            if is_whisper:
                whisper_count += 1
            else:
                whisper_count = 0

            if whisper_count >= WHISPER_FRAMES_REQUIRED:

                whisper_count = 0

                trigger_servo()

            print(
                f"WHISPER={is_whisper} | "
                f"COUNT={whisper_count} | "
                f"RMS={r:.4f} "
                f"ZCR={z:.3f} "
                f"ENT={e:.2f}"
            )

    except KeyboardInterrupt:

        print("\nStopping...")

        proc.terminate()

# -----------------------------
if __name__ == "__main__":
    main()
