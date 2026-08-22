"""Voice-side use of the shared semantic messaging convention."""
from __future__ import annotations

from shared.messaging.events import voice_state
from shared.messaging.topics import TopicNamespace


class VoiceStatePublisher:
    def __init__(self, mqtt_client, *, topic_base="bwm", origin="voice_pi", emit=print):
        self.mqtt_client, self.topic, self.origin, self.emit = mqtt_client, TopicNamespace(topic_base).voice_state, origin, emit

    def publish_transition(self, _previous, state):
        if not self.mqtt_client.publish(self.topic, voice_state(self.origin, state.value)):
            self.emit("[Voice] MQTT state publication unavailable; local lifecycle continues")
