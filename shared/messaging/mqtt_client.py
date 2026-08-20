"""Reusable, failure-isolated MQTT wrapper based on paho-mqtt."""

from dataclasses import dataclass
import logging
import threading
from typing import Callable

from .events import SemanticEvent

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class MQTTSettings:
    enabled: bool = False
    host: str = "localhost"
    port: int = 1883
    client_id: str = "bwm-component"
    qos: int = 1
    reconnect_min_seconds: int = 2
    reconnect_max_seconds: int = 30


class SemanticMQTTClient:
    """paho network loop runs in one idle blocking thread; failures never raise into callers."""

    def __init__(self, settings: MQTTSettings, on_event: Callable[[str, SemanticEvent], None], client_factory=None):
        self.settings, self._on_event, self._client_factory = settings, on_event, client_factory
        self._client = None
        self._connected_event = threading.Event()

    def start(self, subscriptions: list[str]) -> bool:
        if not self.settings.enabled:
            LOG.info("MQTT disabled by configuration")
            return False
        try:
            if self._client_factory is None:
                import paho.mqtt.client as mqtt
                self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.settings.client_id)
            else:
                self._client = self._client_factory(self.settings.client_id)
            self._client.reconnect_delay_set(self.settings.reconnect_min_seconds, self.settings.reconnect_max_seconds)
            self._client.on_connect = lambda client, userdata, flags, reason_code, properties=None: self._connected(client, subscriptions, reason_code)
            self._client.on_disconnect = lambda client, userdata, flags, reason_code, properties=None: LOG.warning("MQTT disconnected: %s", reason_code)
            self._client.on_message = self._message
            self._client.connect_async(self.settings.host, self.settings.port)
            self._client.loop_start()
            return True
        except Exception as exc:
            LOG.warning("MQTT startup unavailable; local operation continues: %s", exc)
            self._client = None
            return False

    def _connected(self, client, subscriptions, reason_code):
        if reason_code != 0:
            LOG.warning("MQTT connection refused: %s", reason_code)
            return
        for topic in subscriptions:
            client.subscribe(topic, qos=self.settings.qos)
        self._connected_event.set()
        LOG.info("MQTT connected; subscribed to %s", ", ".join(subscriptions))

    def _message(self, client, userdata, message):
        try:
            self._on_event(message.topic, SemanticEvent.from_json(message.payload))
        except Exception as exc:
            LOG.warning("Rejected MQTT semantic event on %s: %s", message.topic, exc)

    def publish(self, topic: str, event: SemanticEvent) -> bool:
        if self._client is None:
            LOG.warning("MQTT publish skipped while unavailable")
            return False
        try:
            self._client.publish(topic, event.to_json(), qos=self.settings.qos, retain=False)
            return True
        except Exception as exc:
            LOG.warning("MQTT publish failed: %s", exc)
            return False

    def wait_until_connected(self, timeout: float = 5.0) -> bool:
        """Bounded helper for one-shot tools; runtimes never wait on MQTT."""
        return self._connected_event.wait(timeout)

    def close(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
