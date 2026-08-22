"""Publish one real shared Voice-state MQTT event for Stage 7 smoke tests."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.messaging.config import load_mqtt_settings
from shared.messaging.events import VOICE_STATES, voice_state
from shared.messaging.mqtt_client import SemanticMQTTClient
from shared.messaging.topics import TopicNamespace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("state", choices=sorted(VOICE_STATES))
    parser.add_argument("--origin", default="voice-simulator")
    args = parser.parse_args()
    settings, topic_base = load_mqtt_settings(ROOT)
    settings = settings.__class__(**{**settings.__dict__, "enabled": True,
                                    "client_id": "voice-state-simulator"})
    client = SemanticMQTTClient(settings, lambda topic, event: None)
    if not client.start([]):
        raise SystemExit("MQTT unavailable")
    if not client.wait_until_connected():
        client.close()
        raise SystemExit("MQTT broker did not connect within five seconds")
    published = client.publish(TopicNamespace(topic_base).voice_state,
                               voice_state(args.origin, args.state))
    client.close()
    if not published:
        raise SystemExit("MQTT publish failed")


if __name__ == "__main__":
    main()
