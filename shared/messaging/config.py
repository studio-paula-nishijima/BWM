"""Shared MQTT configuration loader."""
from pathlib import Path
import yaml
from .mqtt_client import MQTTSettings


def load_mqtt_settings(repository_root: Path) -> tuple[MQTTSettings, str]:
    with (repository_root / "configs" / "mqtt.yaml").open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    mqtt = data.get("mqtt", {})
    return MQTTSettings(**{key: mqtt[key] for key in MQTTSettings.__dataclass_fields__ if key in mqtt}), mqtt.get("topic_base", "bwm")
