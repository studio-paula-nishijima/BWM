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

    PROCESSING_MODE,

    SPEECH_DETECTOR_IMPLEMENTATION,
    WHISPER_DETECTOR_IMPLEMENTATION,

    BUFFER_SECONDS,
    
    SPEECH_RMS_MIN,
    SPEECH_RMS_MAX,

    SPEECH_ZCR_MIN,
    SPEECH_ZCR_MAX,

    SPEECH_ENTROPY_MIN,

    SPEECH_CENTROID_MIN,
    SPEECH_CENTROID_MAX,
)


# -----------------------------
# MODULES
# -----------------------------
from whisper.detector import (
    create_whisper_detector,
    create_speech_detector,
)

from whisper.pipeline import (
    DetectorPipeline,
)


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

detector = None


audio_buffer = AudioRingBuffer(
    sample_rate=SAMPLE_RATE,
    buffer_seconds=BUFFER_SECONDS,
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
    global detector


    print("\nShutdown...")

    if detector:
        summary = detector.summary()
        print(
            "Run summary: "
            f"frames={summary['total_frames']} "
            f"speech_positive={summary['speech_positive_frames']} "
            f"whisper_processed={summary['whisper_processed_frames']} "
            f"gated_bypassed={summary['gated_bypassed_frames']} "
            f"whisper_positive={summary['whisper_positive_frames']} "
            f"triggers={summary['trigger_count']}"
        )
        if detector.mode == "shadow":
            print(
                "Shadow disagreement matrix: "
                f"speech_false_whisper_true={summary['speech_false_whisper_true']} "
                f"speech_true_whisper_false={summary['speech_true_whisper_false']} "
                f"speech_true_whisper_true={summary['speech_true_whisper_true']} "
                f"speech_false_whisper_false={summary['speech_false_whisper_false']}"
            )

    if detector:
        detector.reset()


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
    global detector


    # -----------------------------
    # DETECTORS
    # -----------------------------

    whisper_detector = create_whisper_detector(

        WHISPER_DETECTOR_IMPLEMENTATION,

        sample_rate=SAMPLE_RATE,

        rms_min=RMS_MIN,
        rms_max=RMS_MAX,

        zcr_min=ZCR_MIN,
        zcr_max=ZCR_MAX,

        entropy_min=ENTROPY_MIN,

        decision_window=DECISION_WINDOW,
        trigger_ratio=TRIGGER_RATIO

    )


    speech_detector = None


    if PROCESSING_MODE in (
        "speech_gate",
        "shadow"
    ):

        speech_detector = create_speech_detector(

            SPEECH_DETECTOR_IMPLEMENTATION,
        
            sample_rate=SAMPLE_RATE,
        
            rms_min=SPEECH_RMS_MIN,
            rms_max=SPEECH_RMS_MAX,
        
            zcr_min=SPEECH_ZCR_MIN,
            zcr_max=SPEECH_ZCR_MAX,
        
            entropy_min=SPEECH_ENTROPY_MIN,
        
            centroid_min=SPEECH_CENTROID_MIN,
            centroid_max=SPEECH_CENTROID_MAX,
        
        )


    detector = DetectorPipeline(

        whisper_detector,

        speech_detector,

        PROCESSING_MODE

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
        log_file,
        processing_mode=PROCESSING_MODE,
        speech_detector_implementation=(
            SPEECH_DETECTOR_IMPLEMENTATION
            if speech_detector is not None
            else "none"
        ),
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

    # A source open (including a new WAV replay or live-source restart) is a
    # stream boundary, never an ordinary frame boundary.
    detector.reset()



    # -----------------------------
    # START
    # -----------------------------

    start_time = time.time()


    print(
        "Whisper detection running..."
    )


    print(
        f"Processing mode: {PROCESSING_MODE}"
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
                time.time()
                -
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

            audio_buffer.append(
                frame
            )



            # -----------------------------
            # DETECTION
            # -----------------------------

            pipeline_result = detector.process(
                frame
            )


            speech_result = (
                pipeline_result.speech
            )


            result = (
                pipeline_result.whisper
            )


            is_whisper = (
                result.is_whisper
            )



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
                    now
                    -
                    last_trigger_time
                    >
                    COOLDOWN_SECONDS
                ):

                    triggered = True

                    detector.record_trigger()

                    last_trigger_time = now

                    whisper_count = 0



            # -----------------------------
            # LOGGING
            # -----------------------------

            csv_logger.log(
                frame_number,
                pipeline_result,
                triggered
            )



            # -----------------------------
            # DEBUG OUTPUT
            # -----------------------------

            print(
            
                f"SPEECH={speech_result.is_speech if speech_result else 'N/A'} "
                f"SPEECH_PROB={(f'{speech_result.speech_probability:.2f}' if speech_result else 'N/A')} "
                f"GATE={pipeline_result.speech_gate_open} "
                f"WPROC={pipeline_result.whisper_processed} "

                f"WHISPER={is_whisper} "            
                f"COUNT={whisper_count} "            
                f"SCORE={result.raw_score}/3 "            
                f"PROB={result.whisper_probability:.2f} "            
                f"RMS={result.rms:.4f} "            
                f"ZCR={result.zcr:.3f} "            
                f"ENT={result.entropy:.2f} "            
                f"CENT={result.spectral_centroid:.1f} "            
                f"LOW={result.band_energy_low:.3f} "            
                f"MID={result.band_energy_mid:.3f} "            
                f"HIGH={result.band_energy_high:.3f} "            
                f"LR={result.band_ratio_low:.2f} "            
                f"MR={result.band_ratio_mid:.2f} "            
                f"HR={result.band_ratio_high:.2f} "            
                f"TRIGGER={triggered}",

                "\n"
            
            )



    except Exception:

        import traceback

        traceback.print_exc()



    finally:

        shutdown()



if __name__ == "__main__":

    main()
