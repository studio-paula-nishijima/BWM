"""Shared MQTT configuration loader."""
from pathlib import Path
import yaml
from .mqtt_client import MQTTSettings
from .uart import UARTSettings
from .ble import BLESettings


def load_mqtt_settings(repository_root: Path) -> tuple[MQTTSettings, str]:
    with (repository_root / "configs" / "mqtt.yaml").open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    mqtt = data.get("mqtt", {})
    return MQTTSettings(**{key: mqtt[key] for key in MQTTSettings.__dataclass_fields__ if key in mqtt}), mqtt.get("topic_base", "bwm")


def load_uart_settings(repository_root: Path) -> UARTSettings:
    with (repository_root / "configs" / "mqtt.yaml").open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    uart = data.get("uart", {})
    return UARTSettings(**{key: uart[key] for key in UARTSettings.__dataclass_fields__ if key in uart})


def load_ble_settings(repository_root: Path) -> BLESettings:
    with (repository_root / "configs" / "mqtt.yaml").open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    ble = data.get("ble", {})
    return BLESettings(**{key: ble[key] for key in BLESettings.__dataclass_fields__ if key in ble})
