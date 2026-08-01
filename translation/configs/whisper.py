import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

with open(BASE_DIR / "whisper.yaml", "r") as f:
    cfg = yaml.safe_load(f)

SAMPLE_RATE = cfg["sample_rate"]
FRAME_MS = cfg["frame_ms"]
DEVICE = cfg["device"]

DECISION_WINDOW = cfg["decision_window"]
TRIGGER_RATIO = cfg["trigger_ratio"]

WHISPER_FRAMES_REQUIRED = cfg["whisper_frames_required"]
COOLDOWN_SECONDS = cfg["cooldown_seconds"]

RUN_DURATION_SECONDS = cfg["run_duration_seconds"]

RMS_MIN = cfg["rms_min"]
RMS_MAX = cfg["rms_max"]

ZCR_MIN = cfg["zcr_min"]
ZCR_MAX = cfg["zcr_max"]

ENTROPY_MIN = cfg["entropy_min"]

BUFFER_SECONDS = cfg["audio_buffer"]["seconds"]
BUFFER_ENABLED = cfg["audio_buffer"]["enabled"]
