import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

with open(BASE_DIR / "whisper.yaml", "r") as f:
    cfg = yaml.safe_load(f)

SAMPLE_RATE = cfg["sample_rate"]
FRAME_MS = cfg["frame_ms"]
DEVICE = cfg["device"]

RMS_THRESHOLD = cfg["rms_threshold"]
ENTROPY_THRESHOLD = cfg["entropy_threshold"]

DECISION_WINDOW = cfg["decision_window"]
TRIGGER_RATIO = cfg["trigger_ratio"]

WHISPER_FRAMES_REQUIRED = cfg["whisper_frames_required"]
COOLDOWN_SECONDS = cfg["cooldown_seconds"]

RUN_DURATION_SECONDS = cfg["run_duration_seconds"]
