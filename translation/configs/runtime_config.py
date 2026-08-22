from pathlib import Path
import yaml
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_yaml_config(filename):
    """Load a translation configuration relative to this project, not cwd."""
    config_path = PROJECT_ROOT / "configs" / filename
    with config_path.open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file) or {}


def load_runtime_config():
    return load_yaml_config("runtime.yaml")


def load_asr_config():
    return load_yaml_config("asr.yaml")


def load_voice_reactions_config():
    """Load editable Voice reaction definitions and their selection policy."""
    return load_yaml_config("voice_reactions.yaml")


def load_hardware_config():
    return load_yaml_config("hardware.yaml")


def get_solenoid_pin_map(hardware_config=None):
    """Return all configured solenoid outputs without imposing a channel count."""
    hardware_config = hardware_config or load_hardware_config()
    pin_map = hardware_config.get("solenoids", {})
    reserved_pins = set(hardware_config.get("reserved_pins", {}).values())

    if not pin_map:
        raise ValueError("hardware.yaml must configure at least one solenoid output")
    if len(set(pin_map.values())) != len(pin_map):
        raise ValueError("Each configured solenoid output must use a unique GPIO pin")
    if reserved_pins.intersection(pin_map.values()):
        raise ValueError("Reserved GPIO pins cannot be configured as solenoid outputs")

    return dict(pin_map)


def get_backup_button_pin(hardware_config=None):
    hardware_config = hardware_config or load_hardware_config()
    try:
        return hardware_config["controls"]["translation_activation_backup_button"]
    except KeyError as exc:
        raise ValueError("hardware.yaml must configure the translation backup button") from exc


RUNTIME_CONFIG = load_runtime_config()


# ---------------------------------------------------
# Centralized src path injection
# ---------------------------------------------------

SRC_PATH = (
    PROJECT_ROOT /
    RUNTIME_CONFIG["project"]["src_path"]
)

if str(SRC_PATH) not in sys.path:

    sys.path.append(str(SRC_PATH))
