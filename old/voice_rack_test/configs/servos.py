import yaml
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

with open(BASE_DIR / "servos.yaml", "r") as f:
    cfg = yaml.safe_load(f)

SERVO = cfg["servo"]
MOTION = cfg["motion"]

CHANNEL = SERVO["channel"]
FREQUENCY = SERVO["frequency"]

MIN_PULSE = SERVO["min_pulse"]
MAX_PULSE = SERVO["max_pulse"]
HOME_PULSE = SERVO["home_pulse"]

DEFAULT_SPEED = MOTION["default_speed"]
