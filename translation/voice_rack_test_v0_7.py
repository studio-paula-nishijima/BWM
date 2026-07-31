import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from pathlib import Path
from datetime import datetime
import time
import subprocess
import numpy as np
import signal
import select

import argparse


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

    RMS_MIN,
    RMS_MAX,
    ZCR_MIN,
    ZCR_MAX,
    ENTROPY_MIN,

    DECISION_WINDOW,
    TRIGGER_RATIO,

    WHISPER_FRAMES_REQUIRED,
    COOLDOWN_SECONDS,
    RUN_DURATION_SECONDS,
)


# -----------------------------
# MODULES
# -----------------------------
from whisper.detector import WhisperDetector
from audio.wav_source import WavSource
from app_logging.csv_logger import WhisperCSVLogger

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
# -----------------------------f
audio_proc = None
wav_source = None
start_time = None
last_trigger_time = 0
whisper_count = 0
frame_number = 0
csv_logger = None

# -----------------------------
# PARSE ARGUMENTS
# -----------------------------
def parse_arguments():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--wav",
        type=str,
        default=None,
        help="Analyse WAV file instead of live microphone"
    )

    return parser.parse_args()

# -----------------------------
# SHUTDOWN
# -----------------------------
def shutdown(*_):
    global audio_proc
    global csv_logger

    print("\nShutdown...")

    if audio_proc:
        try:
            audio_proc.terminate()
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise
    
    if wav_source:
        try:
            wav_source.close()
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise
            
    try:
        csv_logger.close()
    except Exception:
        print("error closing csv logger")

    raise SystemExit


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)


# -----------------------------
# MAIN LOOP
# -----------------------------
def main():
    global audio_proc, wav_source
    global csv_logger
    global start_time
    global last_trigger_time, whisper_count
    global frame_number

    detector = WhisperDetector(
        sample_rate=SAMPLE_RATE,

        rms_min=RMS_MIN,
        rms_max=RMS_MAX,

        zcr_min=ZCR_MIN,
        zcr_max=ZCR_MAX,

        entropy_min=ENTROPY_MIN,

        decision_window=DECISION_WINDOW,
        trigger_ratio=TRIGGER_RATIO
    )

    args = parse_arguments()
    
    if args.wav:

        wav_path = Path(args.wav)
    
        log_file = (
            Path("logs")
            /
            f"{wav_path.stem}_whisper_analysis.csv"
        )
    
    else:
    
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
    
        log_file = (
            Path("logs")
            /
            f"live_whisper_analysis_{timestamp}.csv"
        )
    
    
    csv_logger = WhisperCSVLogger(
        log_file
    )
    
    print(
        f"Logging to: {log_file}"
    )


    if args.wav:

        print(
            f"WAV mode: {args.wav}"
        )

        wav_source = WavSource(
            args.wav,
            SAMPLE_RATE,
            FRAME_SIZE
        )

        audio_proc = None

    else:

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
            if wav_source:

                frame = wav_source.read_frame()
            
                if frame is None:
                    print("WAV complete")
                    break
            
            else:
            
                r, _, _ = select.select(
                    [audio_proc.stdout],
                    [],
                    [],
                    1.0
                )
            
                if not r:
                    continue
            
            
                data = audio_proc.stdout.read(
                    FRAME_BYTES
                )
            
                if len(data) != FRAME_BYTES:
                    continue
            
            
                frame = (
                    np.frombuffer(
                        data,
                        dtype=np.int16
                    )
                    .astype(np.float32)
                    /
                    32768.0
                )
                
            frame_number += 1


            # -----------------------------
            # WHISPER DETECTION
            # -----------------------------
            result = detector.classify(frame)

            is_whisper = result.is_whisper

            rms_v = result.rms
            zcr_v = result.zcr
            ent_v = result.entropy


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
                    
            csv_logger.log(
                frame_number,
                result,
                triggered
            )


            # -----------------------------
            # DEBUG OUTPUT
            # -----------------------------
            print(
                f"WHISPER={is_whisper} "
                f"COUNT={whisper_count} "
                f"SCORE={result.raw_score}/3 "
                f"PROB={result.whisper_probability:.2f} "
                f"RMS={rms_v:.4f} "
                f"ZCR={zcr_v:.3f} "
                f"ENT={ent_v:.2f} "
                f"TRIGGER={triggered}"
            )


    except Exception:
        import traceback
        traceback.print_exc()

    finally:
        shutdown()


if __name__ == "__main__":
    main()
