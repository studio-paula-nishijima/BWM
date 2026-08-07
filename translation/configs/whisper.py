import yaml
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


with open(BASE_DIR / "whisper.yaml", "r") as f:
    cfg = yaml.safe_load(f)


# -----------------------------
# AUDIO
# -----------------------------

SAMPLE_RATE = cfg["sample_rate"]

FRAME_MS = cfg["frame_ms"]

DEVICE = cfg["device"]



# -----------------------------
# DETECTOR MODES
# -----------------------------

PROCESSING_MODE = cfg.get(
    "processing_mode",
    "direct"
)


SPEECH_DETECTOR_IMPLEMENTATION = (
    cfg
    .get("speech_detector", {})
    .get("implementation", "feature")
)


# -----------------------------
# SPEECH FEATURES
# -----------------------------

speech_cfg = cfg.get(
    "speech_detector",
    {}
)

SPEECH_RMS_MIN = speech_cfg.get(
    "rms_min",
    0.003
)

SPEECH_RMS_MAX = speech_cfg.get(
    "rms_max",
    0.20
)

SPEECH_ZCR_MIN = speech_cfg.get(
    "zcr_min",
    0.02
)

SPEECH_ZCR_MAX = speech_cfg.get(
    "zcr_max",
    0.40
)

SPEECH_ENTROPY_MIN = speech_cfg.get(
    "entropy_min",
    3.0
)

SPEECH_CENTROID_MIN = speech_cfg.get(
    "centroid_min",
    300
)

SPEECH_CENTROID_MAX = speech_cfg.get(
    "centroid_max",
    4000
)

# -----------------------------
# WHISPER FEATURES
# -----------------------------

WHISPER_DETECTOR_IMPLEMENTATION = (
    cfg
    .get("whisper_detector", {})
    .get("implementation", "feature")
)

WHISPER_CLASSIFIER_CONFIG = cfg.get("whisper_classifier", {})
WHISPER_CLASSIFIER_IMPLEMENTATION = WHISPER_CLASSIFIER_CONFIG.get(
    "implementation", "legacy"
)
WHISPER_CLASSIFIER_COMPARE_IMPLEMENTATION = WHISPER_CLASSIFIER_CONFIG.get(
    "compare_implementation"
)
WHISPER_CLASSIFIER_SETTINGS = {
    key: value for key, value in WHISPER_CLASSIFIER_CONFIG.items()
    if key not in {"implementation", "compare_implementation"}
}



# -----------------------------
# TEMPORAL SETTINGS
# -----------------------------

DECISION_WINDOW = cfg["decision_window"]

TRIGGER_RATIO = cfg["trigger_ratio"]

WHISPER_FRAMES_REQUIRED = (
    cfg["whisper_frames_required"]
)

COOLDOWN_SECONDS = (
    cfg["cooldown_seconds"]
)

RUN_DURATION_SECONDS = (
    cfg["run_duration_seconds"]
)



# -----------------------------
# WHISPER FEATURES
# -----------------------------

RMS_MIN = cfg["rms_min"]

RMS_MAX = cfg["rms_max"]

ZCR_MIN = cfg["zcr_min"]

ZCR_MAX = cfg["zcr_max"]

ENTROPY_MIN = cfg["entropy_min"]



# -----------------------------
# BUFFER
# -----------------------------

BUFFER_SECONDS = (
    cfg["audio_buffer"]["seconds"]
)

BUFFER_ENABLED = (
    cfg["audio_buffer"]["enabled"]
)
