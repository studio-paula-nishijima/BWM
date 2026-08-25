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
sys.path.insert(0, os.path.dirname(BASE_DIR))  # repository root: shared/messaging


from pathlib import Path
from datetime import datetime
from dataclasses import replace
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
    ANALYSIS_FILENAME_TAG,
    DETECTOR_PROFILE,
    DETECTOR_PROFILES,
    LIVE_DIAGNOSTIC_LOGGING,

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
    SPEECH_DETECTOR_COMPARE_IMPLEMENTATION,
    SPEECH_WEBRTC_AGGRESSIVENESS,
    SPEECH_WEBRTC_COMPARE_AGGRESSIVENESS_MODES,
    WHISPER_DETECTOR_IMPLEMENTATION,
    WHISPER_CLASSIFIER_SETTINGS,
    WHISPER_CLASSIFIER_IMPLEMENTATION,
    WHISPER_CLASSIFIER_COMPARE_IMPLEMENTATION,

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
from whisper.profiles import PROFILE_NAMES, TemporalProfilePolicy


from audio.wav_source import WavSource
from audio.arecord_source import ArecordSource
from src.audio.ring_buffer import AudioRingBuffer
from audio.utterance_capture import CapturePolicy, UtteranceCaptureController
from live.asr_worker import ASRWorkerConfig, PersistentASRWorker
from live.voice_runtime import LiveASRCoordinator, VoiceLifecycle
from live.interaction import OracleInteractionController
from live.oracle_display import DisplayConfig, OracleDisplayController, PygameOracleDisplayController
from live.retrieval_adapter import RiverCultureRetrievalAdapter
from live.retrieval_worker import PersistentRetrievalWorker
from live.voice_messaging import VoiceStatePublisher
from configs.runtime_config import load_asr_config

from app_logging.csv_logger import WhisperCSVLogger
from actuation.runtime import resolve_actuation_enabled, DelayedInteractionServo
from actuation.servo_controller import ServoActuationController
from configs.servos import CHANNEL, FREQUENCY, MIN_PULSE, MAX_PULSE, HOME_PULSE, DELAY_SECONDS



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
actuation_controller = None
run_configuration_summary = None
asr_coordinator = None
oracle_interaction = None
voice_mqtt = None
voice_uart = None
interaction_servo = None
shutdown_started = False


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

    parser.add_argument(
        "--analysis-tag",
        type=str,
        default=None,
        help="Optional filename tag for analysis logs, e.g. 3L",
    )
    parser.add_argument("--enable-live-logging", action="store_true", help="Enable diagnostic CSV logging for this live run without changing configuration")
    parser.add_argument("--diagnostic-console", action="store_true", help="Show per-frame detector telemetry (normal live output is event based)")
    parser.add_argument("--no-live-asr", action="store_true", help="Capture normally but do not start the live ASR worker")
    parser.add_argument("--asr-model", choices=("tiny", "base", "small"), default=None, help="Override the configured live Faster-Whisper model")
    parser.add_argument("--release-after-asr", action="store_true", help="Debug only: reopen interaction admission after each ASR result")
    parser.add_argument("--oracle", dest="oracle", action="store_true", default=True,
                        help="Enable Oracle response integration (the default)")
    parser.add_argument("--no-oracle", dest="oracle", action="store_false",
                        help="Disable retrieval and the Oracle display for capture/ASR-only runs")
    parser.add_argument("--oracle-headless", action="store_true", help="Use the deterministic no-screen Oracle display controller")
    parser.add_argument("--oracle-width", type=int, default=800, help="Oracle window/test width")
    parser.add_argument("--oracle-height", type=int, default=480, help="Oracle window/test height")
    parser.add_argument("--oracle-fullscreen", action="store_true", help="Select fullscreen Oracle display mode")
    parser.add_argument("--oracle-response-seconds", type=float, default=8.0, help="Minimum static response duration")
    parser.add_argument("--oracle-max-response-seconds", type=float, default=8.0,
                        help="Demo cap for total response presentation (0 disables cap)")
    parser.add_argument("--voice-mqtt", action="store_true", help="Publish shared voice.state transitions through configured MQTT")
    uart_group = parser.add_mutually_exclusive_group()
    uart_group.add_argument("--voice-uart", dest="voice_uart", action="store_true", default=True,
                            help="Publish shared voice.state transitions through configured UART (default)")
    uart_group.add_argument("--no-voice-uart", dest="voice_uart", action="store_false",
                            help="Disable UART publication for an MQTT-only or standalone run")
    parser.add_argument("--detector-profile", choices=PROFILE_NAMES, default=None)
    parser.add_argument("--processing-mode", choices=("direct", "speech_gate", "shadow"), default=None)
    actuation_group = parser.add_mutually_exclusive_group()
    actuation_group.add_argument("--enable-actuation", action="store_true", help="Enable physical servo actuation (WAV opt-in)")
    actuation_group.add_argument("--no-actuation", action="store_true", help="Run without initialising servo hardware")

    return parser.parse_args()



# -----------------------------
# SHUTDOWN
# -----------------------------

def _begin_shutdown():
    """Return true once; SIGINT and ``finally`` may both request shutdown."""
    global shutdown_started
    if shutdown_started:
        return False
    shutdown_started = True
    return True


def shutdown(*_):

    global source
    global csv_logger
    global detector
    global actuation_controller
    global run_configuration_summary
    global asr_coordinator
    global oracle_interaction
    global voice_mqtt, voice_uart, interaction_servo

    if not _begin_shutdown():
        return


    print("\nShutdown...")
    if run_configuration_summary:
        print("Run configuration recap:\n" + run_configuration_summary)

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

    if asr_coordinator:
        try:
            asr_coordinator.shutdown()
        except Exception:
            import traceback
            traceback.print_exc()
    if oracle_interaction:
        oracle_interaction.close()
    if voice_mqtt:
        voice_mqtt.close()
    if voice_uart:
        voice_uart.close()

    if actuation_controller:
        if interaction_servo: interaction_servo.cancel()
        try:
            actuation_controller.shutdown()
        except Exception:
            import traceback
            traceback.print_exc()


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
    global actuation_controller
    global run_configuration_summary
    global asr_coordinator
    global oracle_interaction
    global voice_mqtt, voice_uart, interaction_servo

    args = parse_arguments()
    asr_config = load_asr_config().get("asr", {})
    actuation_enabled = resolve_actuation_enabled(wav_path=args.wav, enable_actuation=args.enable_actuation, no_actuation=args.no_actuation)
    detector_profile = args.detector_profile or DETECTOR_PROFILE
    profile_settings = dict(DETECTOR_PROFILES.get(detector_profile, {}))
    if detector_profile not in PROFILE_NAMES:
        raise RuntimeError("Unknown detector profile; choose " + ", ".join(PROFILE_NAMES))
    resolved_processing_mode = args.processing_mode or PROCESSING_MODE
    classifier_implementation = "temporal_v2" if detector_profile in ("temporal_v2_context", "temporal_v2_recall") else "temporal_v1"
    comparison_implementation = WHISPER_CLASSIFIER_COMPARE_IMPLEMENTATION if detector_profile == "analysis_full" else None
    profile_policy = TemporalProfilePolicy(detector_profile, profile_settings)
    temporal_settings = {**WHISPER_CLASSIFIER_SETTINGS, **profile_settings, "analysis_full": detector_profile == "analysis_full"}

    if (
        resolved_processing_mode == "direct" or SPEECH_DETECTOR_IMPLEMENTATION != "silero"
    ):
        raise RuntimeError(
            "Silero-evidence classifiers require processing_mode speech_gate/shadow and "
            "speech_detector.implementation: silero"
        )


    # -----------------------------
    # DETECTORS
    # -----------------------------

    whisper_detector = create_whisper_detector(

        classifier_implementation,

        sample_rate=SAMPLE_RATE,

        rms_min=RMS_MIN,
        rms_max=RMS_MAX,

        zcr_min=ZCR_MIN,
        zcr_max=ZCR_MAX,

        entropy_min=ENTROPY_MIN,

        decision_window=DECISION_WINDOW,
        trigger_ratio=TRIGGER_RATIO,
        **temporal_settings,

    )


    speech_detector = None
    comparison_speech_detectors = {}


    if True:

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
        if detector_profile in ("webrtc_assisted_temporal", "temporal_v2_context", "temporal_v2_recall"):
            comparison_speech_detectors[profile_settings["webrtc_aggressiveness"]] = create_speech_detector(
                "webrtc", sample_rate=SAMPLE_RATE, aggressiveness=profile_settings["webrtc_aggressiveness"]
            )
        elif detector_profile == "analysis_full":
            for aggressiveness in sorted(set(SPEECH_WEBRTC_COMPARE_AGGRESSIVENESS_MODES + [3])):
                comparison_speech_detectors[aggressiveness] = create_speech_detector(
                    SPEECH_DETECTOR_COMPARE_IMPLEMENTATION,
                    sample_rate=SAMPLE_RATE,
                    aggressiveness=aggressiveness,
                )


    comparison_whisper_detectors = {}
    if comparison_implementation:
        comparison_whisper_detectors[comparison_implementation] = create_whisper_detector(
            comparison_implementation,
            sample_rate=SAMPLE_RATE,
            rms_min=RMS_MIN, rms_max=RMS_MAX, zcr_min=ZCR_MIN,
            zcr_max=ZCR_MAX, entropy_min=ENTROPY_MIN,
            decision_window=DECISION_WINDOW, trigger_ratio=TRIGGER_RATIO,
            **WHISPER_CLASSIFIER_SETTINGS
        )
    if detector_profile == "analysis_full" and "legacy" not in comparison_whisper_detectors:
        comparison_whisper_detectors["legacy"] = create_whisper_detector(
            "legacy",
            sample_rate=SAMPLE_RATE,
            rms_min=RMS_MIN, rms_max=RMS_MAX, zcr_min=ZCR_MIN,
            zcr_max=ZCR_MAX, entropy_min=ENTROPY_MIN,
            decision_window=DECISION_WINDOW, trigger_ratio=TRIGGER_RATIO,
        )

    detector = DetectorPipeline(

        whisper_detector,

        speech_detector,

        resolved_processing_mode,
        comparison_whisper_detectors=comparison_whisper_detectors,
        comparison_speech_detectors=comparison_speech_detectors,
        classifier_implementation=classifier_implementation,

    )


    # -----------------------------
    # LOG FILE
    # -----------------------------

    selected_analysis_tag = (
        args.analysis_tag
        if args.analysis_tag is not None
        else f"{ANALYSIS_FILENAME_TAG}_{detector_profile}" if ANALYSIS_FILENAME_TAG else detector_profile
    )
    analysis_tag = f"_{selected_analysis_tag}" if selected_analysis_tag else ""
    log_directory = Path("logs") / selected_analysis_tag if selected_analysis_tag else Path("logs")

    if args.wav:

        wav_path = Path(
            args.wav
        )

        log_file = (
            log_directory
            /
            f"{wav_path.stem}{analysis_tag}_whisper_analysis.csv"
        )

    else:

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        log_file = (
            log_directory
            /
            f"live{analysis_tag}_whisper_analysis_{timestamp}.csv"
        )


    logging_enabled = bool(args.wav or args.enable_live_logging or detector_profile == "analysis_full" or LIVE_DIAGNOSTIC_LOGGING.get("enabled", False))
    csv_logger = WhisperCSVLogger(
        log_file,
        processing_mode=PROCESSING_MODE,
        speech_detector_implementation=(
            SPEECH_DETECTOR_IMPLEMENTATION
            if speech_detector is not None
            else "none"
        ),
        comparison_speech_detector_implementation="webrtc" if comparison_speech_detectors else None,
        comparison_speech_modes=tuple(comparison_speech_detectors),
        whisper_classifier_implementation=classifier_implementation,
        detector_profile=detector_profile,
        actuation_enabled=actuation_enabled,
    ) if logging_enabled else None


    print(
        f"Logging to: {log_file}" if logging_enabled else "Diagnostic CSV logging disabled"
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
    profile_policy.reset()

    if actuation_enabled:
        actuation_config = {"channel": CHANNEL, "frequency": FREQUENCY, "min_pulse": MIN_PULSE, "max_pulse": MAX_PULSE, "home_pulse": HOME_PULSE, "cooldown_seconds": COOLDOWN_SECONDS}
        try:
            actuation_controller = ServoActuationController(actuation_config)
        except Exception as exc:
            try: source.close()
            except Exception: pass
            if csv_logger:
                try: csv_logger.close()
                except Exception: pass
            raise RuntimeError("Actuation initialisation failed. Check PCA9685/I2C/servo dependencies, or rerun with --no-actuation to test detection without hardware.") from exc
    interaction_servo = DelayedInteractionServo(actuation_controller, DELAY_SECONDS)

    # Capture and ASR are additional downstream consumers.  They receive only
    # real emitted triggers, after cooldown, and do not alter detector/servo work.
    capture_policy = CapturePolicy(pre_roll_seconds=4.0, end_silence_seconds=None,
                                   post_roll_seconds=0.0, max_utterance_seconds=12.0)
    capture_controller = UtteranceCaptureController(SAMPLE_RATE, audio_buffer, capture_policy,
                                                     args.wav or "live_respeaker", detector_profile)
    worker_enabled = bool(asr_config.get("worker_enabled", True)) and not args.no_live_asr
    worker = PersistentASRWorker(ASRWorkerConfig(
        backend=asr_config.get("backend", "faster_whisper"), model=args.asr_model or asr_config.get("model", "base"),
        device=asr_config.get("device", "cpu"), compute_type=asr_config.get("compute_type", "int8"),
        cpu_threads=asr_config.get("cpu_threads", 2), worker_nice=asr_config.get("worker_nice", 10),
        queue_size=asr_config.get("queue_size", 1),
    )) if worker_enabled else None
    lifecycle = VoiceLifecycle()
    retrieval = None
    if args.oracle:
        retrieval = PersistentRetrievalWorker(Path(BASE_DIR).parent)
        print("[RetrievalWorker] starting")
        retrieval.start()
    def retrieval_ready():
        if retrieval is None: return True, ""
        if retrieval.ready: return True, ""
        return False, retrieval.startup_error or ""
    asr_coordinator = LiveASRCoordinator(capture_controller, worker, lifecycle=lifecycle,
                                         source_id=args.wav or "live_respeaker", detector_profile=detector_profile,
                                         release_after_asr=args.release_after_asr, startup_ready=retrieval_ready,
                                         inference_timeout_seconds=asr_config.get("inference_timeout_seconds"),
                                         on_capture_started=interaction_servo.schedule)
    if args.oracle:
        display_config = DisplayConfig(width=args.oracle_width, height=args.oracle_height,
            fullscreen=args.oracle_fullscreen, enabled=not args.oracle_headless,
            minimum_response_seconds=args.oracle_response_seconds,
            max_response_seconds=args.oracle_max_response_seconds or None)
        display = OracleDisplayController(display_config) if args.oracle_headless else PygameOracleDisplayController(display_config)
        oracle_interaction = OracleInteractionController(asr_coordinator, retrieval, display)
        lifecycle.add_transition_observer(oracle_interaction.on_voice_transition)
    if args.voice_mqtt or args.voice_uart:
        from shared.messaging.config import load_mqtt_settings, load_uart_settings
        from shared.messaging.mqtt_client import SemanticMQTTClient
        from shared.messaging.uart import SemanticUARTTransport
        settings, topic_base = load_mqtt_settings(Path(BASE_DIR).parent)
        if args.voice_mqtt:
            voice_mqtt = SemanticMQTTClient(settings, lambda *_: None)
            voice_mqtt.start([])
        if args.voice_uart:
            # The CLI explicitly selects Voice UART publication.  The YAML
            # carries device/framing settings; Translation opens its enabled
            # shared UART ingress independently.
            voice_uart = SemanticUARTTransport(
                replace(load_uart_settings(Path(BASE_DIR).parent), enabled=True),
                lambda *_: None,
            )
            voice_uart.start()
        lifecycle.add_transition_observer(VoiceStatePublisher(voice_mqtt, uart_transport=voice_uart, topic_base=topic_base).publish_transition)
    asr_coordinator.start()



    # -----------------------------
    # START
    # -----------------------------

    start_time = time.time()


    print(
        "Whisper detection running..."
    )


    run_configuration_summary = "\n".join((
        f"Detector profile: {detector_profile}", f"Processing mode: {resolved_processing_mode}",
        f"Audio source: {'WAV' if args.wav else 'live'}", f"Actuation: {'enabled' if actuation_enabled else 'disabled'}",
        f"Whisper classifier: {classifier_implementation}",
    ))
    print(run_configuration_summary)
    print(f"Live ASR: {'enabled' if worker_enabled else 'disabled'}; model={args.asr_model or asr_config.get('model', 'base')}; language=auto")
    if detector_profile in ("webrtc_assisted_temporal", "temporal_v2_context", "temporal_v2_recall"):
        print(f"Trigger policy: WebRTC assist {profile_settings['assisted_confirmation_frames']} frames; temporal fallback {profile_settings['fallback_confirmation_frames']} frames")
        print(f"WebRTC debounce: enter {profile_settings['webrtc_enter_frames']} / exit {profile_settings['webrtc_exit_frames']} frames")
        run_configuration_summary += f"\nTrigger policy: WebRTC assist {profile_settings['assisted_confirmation_frames']} frames; temporal fallback {profile_settings['fallback_confirmation_frames']} frames\nWebRTC debounce: enter {profile_settings['webrtc_enter_frames']} / exit {profile_settings['webrtc_exit_frames']} frames"
        if "context_confirmation_frames" in profile_settings:
            context_line = f"Context: {'enabled' if profile_settings.get('context_enabled') else 'disabled'}; {profile_settings.get('context_window_frames', 0)} frames at ≥{profile_settings.get('context_silero_threshold', 0)} ({profile_settings.get('context_min_frames', 0)} minimum); confirmation {profile_settings['context_confirmation_frames']} frames"
            print(context_line)
            run_configuration_summary += "\n" + context_line
    else:
        print(f"Trigger policy: temporal only, {profile_settings['fallback_confirmation_frames']} frames")
        run_configuration_summary += f"\nTrigger policy: temporal only, {profile_settings['fallback_confirmation_frames']} frames"
    print(f"Temporal window: {profile_settings['rolling_window_frames']} frames; Silero median range: {profile_settings['silero_median_min']}–{profile_settings['silero_median_max']}; low-proportion std minimum: {profile_settings['low_proportion_std_min']}")
    run_configuration_summary += f"\nTemporal window: {profile_settings['rolling_window_frames']} frames; Silero median range: {profile_settings['silero_median_min']}–{profile_settings['silero_median_max']}; low-proportion std minimum: {profile_settings['low_proportion_std_min']}"


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
                completed_asr = asr_coordinator.finish_capture()
                if oracle_interaction:
                    oracle_interaction.on_asr_results(completed_asr)
                    oracle_interaction.poll()
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


            is_whisper = result.is_whisper
            # Mode 0 is the configured assisted gate and is always present for
            # both the assisted and analysis_full profiles.
            assist_result = pipeline_result.speech_comparisons.get(profile_settings.get("webrtc_aggressiveness", 0))
            profile_decision = profile_policy.update(result, assist_result)
            result.detector_profile = detector_profile
            result.webrtc_assist_open = profile_decision.webrtc_assist_open
            result.webrtc_assist_enter_count = profile_decision.webrtc_enter_count
            result.webrtc_assist_exit_count = profile_decision.webrtc_exit_count
            result.temporal_candidate = result.temporal_v2_raw_is_whisper if classifier_implementation == "temporal_v2" else result.temporal_v1_raw_is_whisper
            result.temporal_qualifying_run = result.temporal_v2_qualifying_run if classifier_implementation == "temporal_v2" else result.temporal_v1_qualifying_run
            result.assisted_confirmation_requirement = profile_decision.assisted_confirmation_requirement
            result.fallback_confirmation_requirement = profile_decision.fallback_confirmation_requirement
            result.context_confirmation_requirement = profile_decision.context_confirmation_requirement
            result.confirmation_requirement = profile_decision.confirmation_requirement
            result.threshold_crossing_route = profile_decision.trigger_route
            result.trigger_route = None
            result.trigger_suppression_reason = None



            triggered = False

            now = time.time()


            if profile_decision.trigger and now - last_trigger_time > COOLDOWN_SECONDS:
                triggered = True
                detector.record_trigger()
                last_trigger_time = now
                result.trigger_route = profile_decision.trigger_route
            elif profile_decision.trigger:
                # A threshold crossing is still logged, but it is not an
                # emitted trigger while the actuator cooldown is active.
                result.trigger_suppression_reason = "cooldown"

            actuation_result = None

            # Polling only reads already-completed results; ASR remains in its
            # persistent child process while the next detector frame proceeds.
            completed_asr = asr_coordinator.process_frame(frame, frame_number, emitted_trigger=triggered,
                                                           temporal_candidate=bool(result.temporal_candidate))
            if oracle_interaction:
                oracle_interaction.on_asr_results(completed_asr)
                oracle_interaction.poll()
            asr_coordinator.ready_status()



            # -----------------------------
            # LOGGING
            # -----------------------------

            if csv_logger:
                csv_logger.log(frame_number, pipeline_result, triggered, actuation_result)
                max_log_frames = LIVE_DIAGNOSTIC_LOGGING.get("max_frames", 0)
                if not args.wav and detector_profile != "analysis_full" and max_log_frames and frame_number + 1 >= max_log_frames:
                    csv_logger.close()
                    csv_logger = None



            # -----------------------------
            # DEBUG OUTPUT
            # -----------------------------

            if args.diagnostic_console or args.wav or detector_profile == "analysis_full": print(
            
                f"SPEECH={speech_result.is_speech if speech_result else 'N/A'} "
                f"SPEECH_PROB={(f'{speech_result.speech_probability:.2f}' if speech_result else 'N/A')} "
                f"GATE={pipeline_result.speech_gate_open} "
                f"WPROC={pipeline_result.whisper_processed} "

                f"WHISPER={is_whisper} "            
                f"COUNT={result.temporal_qualifying_run if result.temporal_qualifying_run is not None else 0} "
                f"SCORE={result.raw_score}/3 "            
                f"PROB={result.whisper_probability:.2f} "            
                f"CAND={result.stage1_candidate if result.stage1_candidate is not None else 'N/A'} "
                f"GRP={result.group_count if result.group_count is not None else 'N/A'} "
                f"EFF={result.effective_group_score if result.effective_group_score is not None else 'N/A'} "
                f"HSIL={result.high_silero_normal_evidence if result.high_silero_normal_evidence is not None else 'N/A'} "
                f"V2_CAND={result.temporal_v2_raw_is_whisper if classifier_implementation == 'temporal_v2' else 'N/A'} "
                f"SILERO_MED={(f'{result.temporal_v2_silero_median:.3e}' if result.temporal_v2_silero_median is not None else 'N/A')} "
                f"LOW_STD={(f'{result.low_proportion_std:.3e}' if result.low_proportion_std is not None else 'N/A')} "
                f"ZCR_STD={(f'{result.zcr_std:.3e}' if result.zcr_std is not None else 'N/A')} "
                f"ACTIVITY={(f'{result.temporal_v2_acoustic_activity:.3e}' if result.temporal_v2_acoustic_activity is not None else 'N/A')} "
                f"ACTIVITY_OK={result.temporal_v2_acoustic_activity_ok if classifier_implementation == 'temporal_v2' else 'N/A'} "
                f"V2_RUN={result.temporal_v2_qualifying_run if classifier_implementation == 'temporal_v2' else 'N/A'} "
                f"WASSIST={result.webrtc_assist_open if result.webrtc_assist_open is not None else 'N/A'} "
                f"CROSS={result.threshold_crossing_route or 'N/A'} "
                f"ROUTE={result.trigger_route or 'N/A'} "
                f"CLASSIFIER={result.whisper_classifier_implementation or WHISPER_CLASSIFIER_IMPLEMENTATION} "
                f"RMS={result.rms:.3e} "
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
