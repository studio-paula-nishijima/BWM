import sys
import os

# -----------------------------
# PATH SETUP
# -----------------------------
BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

sys.path.insert(
    0,
    os.path.join(BASE_DIR, "src")
)


from pathlib import Path
from datetime import datetime
import time
import signal
import argparse


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
from audio.arecord_source import ArecordSource
from src.audio.ring_buffer import AudioRingBuffer

from app_logging.csv_logger import WhisperCSVLogger


# -----------------------------
# AUDIO FRAME SIZE
# -----------------------------
FRAME_SIZE = int(
    SAMPLE_RATE *
    FRAME_MS /
    1000
)


# -----------------------------
# STATE
# -----------------------------
source = None

start_time = None

last_trigger_time = 0

whisper_count = 0

csv_logger = None

audio_buffer = AudioRingBuffer(
    sample_rate=16000,
    buffer_seconds=5,
)


# -----------------------------
# ARGUMENTS
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

    global source
    global csv_logger


    print("\nShutdown...")


    if source:

        try:
            source.close()

        except Exception:

            import traceback
            traceback.print_exc()


    if csv_logger:

        try:
            csv_logger.close()

        except Exception:

            print(
                "error closing csv logger"
            )


    raise SystemExit


signal.signal(
    signal.SIGINT,
    shutdown
)

signal.signal(
    signal.SIGTERM,
    shutdown
)


# -----------------------------
# MAIN LOOP
# -----------------------------
def main():

    global source
    global csv_logger

    global start_time

    global last_trigger_time
    global whisper_count


    # -----------------------------
    # DETECTOR
    # -----------------------------
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


    # -----------------------------
    # LOG FILE
    # -----------------------------
    if args.wav:

        wav_path = Path(
            args.wav
        )

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


    # -----------------------------
    # AUDIO SOURCE
    # -----------------------------
    if args.wav:

        print(
            f"WAV mode: {args.wav}"
        )


        source = WavSource(

            args.wav,

            SAMPLE_RATE,

            FRAME_SIZE
        )


    else:

        source = ArecordSource(

            DEVICE,

            SAMPLE_RATE,

            FRAME_SIZE
        )


    source.open()


    # -----------------------------
    # START
    # -----------------------------
    start_time = time.time()


    print(
        "Whisper detection running..."
    )

    print(
        "No servo control enabled"
    )


    try:

        while True:


            # -----------------------------
            # TIME LIMIT
            # -----------------------------
            if (
                time.time() -
                start_time
                >
                RUN_DURATION_SECONDS
            ):

                print(
                    "Run time complete"
                )

                break



            # -----------------------------
            # AUDIO READ
            # -----------------------------
            audio_frame = (
                source.read_frame()
            )


            if audio_frame is None:

                print(
                    "Audio source complete"
                )

                break



            frame = (
                audio_frame.samples
            )


            frame_number = (
                audio_frame.frame_number
            )

            # -----------------------------
            # RING BUFFER
            # -----------------------------
            
            audio_buffer.append(frame)

            # -----------------------------
            # WHISPER DETECTION
            # -----------------------------
            result = detector.classify(
                frame
            )


            is_whisper = (
                result.is_whisper
            )


            rms_v = result.rms
            zcr_v = result.zcr
            ent_v = result.entropy



            if is_whisper:

                whisper_count += 1

            else:

                whisper_count = 0



            triggered = False

            now = time.time()


            if (
                whisper_count
                >=
                WHISPER_FRAMES_REQUIRED
            ):

                if (
                    now -
                    last_trigger_time
                    >
                    COOLDOWN_SECONDS
                ):

                    triggered = True

                    last_trigger_time = now

                    whisper_count = 0



            # -----------------------------
            # LOGGING
            # -----------------------------
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
