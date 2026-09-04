"""Voice-side use of the shared semantic messaging convention."""
from __future__ import annotations

from shared.messaging.events import whisper_interaction, whisper_state
from shared.messaging.topics import TopicNamespace


class VoiceLifecyclePublisher:
    """Publish Voice interaction-lifecycle transitions without changing their wire contract."""
    """Build one authoritative event then fan it out without changing its identity."""
    def __init__(self, mqtt_client=None, *, uart_transport=None, topic_base="bwm", origin="whisper_pi", emit=print):
        self.mqtt_client, self.uart_transport = mqtt_client, uart_transport
        self.topic, self.origin, self.emit = TopicNamespace(topic_base).whisper_state, origin, emit

    def publish_transition(self, _previous, state):
        event = whisper_state(self.origin, state.value)
        delivered = False
        if self.mqtt_client is not None:
            if self.mqtt_client.publish(self.topic, event):
                delivered = True
                self.emit(f"[VoiceMessaging] whisper.state {state.value} sent via MQTT")
            else:
                self.emit(f"[VoiceMessaging] whisper.state {state.value} failed via MQTT; local lifecycle continues")
        if self.uart_transport is not None:
            if self.uart_transport.send(event):
                delivered = True
                self.emit(f"[VoiceMessaging] whisper.state {state.value} sent via UART")
            else:
                self.emit(f"[VoiceMessaging] whisper.state {state.value} failed via UART; local lifecycle continues")
        if not delivered:
            self.emit("[VoiceMessaging] all state transports unavailable; local lifecycle continues")


class VoiceInteractionPublisher:
    """Fan out one post-cooldown interaction envelope without changing its ID."""
    def __init__(self, mqtt_client=None, *, uart_transport=None, topic_base="bwm", origin="whisper_pi", emit=print):
        self.mqtt_client, self.uart_transport = mqtt_client, uart_transport
        self.topic, self.origin, self.emit = TopicNamespace(topic_base).whisper_interaction, origin, emit

    def publish(self, source, silero_selection_value=None):
        event = whisper_interaction(self.origin, source, silero_selection_value=silero_selection_value)
        delivered = False
        if self.mqtt_client is not None:
            delivered = bool(self.mqtt_client.publish(self.topic, event))
        if self.uart_transport is not None:
            delivered = bool(self.uart_transport.send(event)) or delivered
        if not delivered:
            self.emit("[VoiceMessaging] interaction transports unavailable; local feedback continues")
        return event
