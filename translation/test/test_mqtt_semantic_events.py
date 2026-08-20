import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRANSLATION_ROOT = ROOT / "translation"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TRANSLATION_ROOT / "src"))

from runtime.clock import SimulatedClock
from runtime.mqtt_adapter import TranslationMQTTAdapter
from runtime.session import PlaybackSessionRuntime
from shared.messaging.deduplication import RecentEventIds
from shared.messaging.events import EventValidationError, SemanticEvent, installation_activation
from shared.messaging.mqtt_client import MQTTSettings, SemanticMQTTClient
from shared.messaging.topics import TopicNamespace


class Dispatcher:
    def dispatch(self, event):
        pass


class FakeMQTT:
    def __init__(self):
        self.subscriptions, self.published = [], []
    def reconnect_delay_set(self, minimum, maximum): self.delay = (minimum, maximum)
    def connect_async(self, host, port): self.connection = (host, port)
    def loop_start(self): pass
    def loop_stop(self): pass
    def disconnect(self): pass
    def subscribe(self, topic, qos): self.subscriptions.append((topic, qos))
    def publish(self, topic, payload, qos, retain): self.published.append((topic, payload, qos, retain))


class SemanticMessagingTests(unittest.TestCase):
    def setUp(self):
        self.clock = SimulatedClock()
        self.sessions = [[{"playback_time": 0, "target": "one"}], [{"playback_time": 0, "target": "two"}]]
        self.runtime = PlaybackSessionRuntime(lambda: self.sessions.pop(0), self.clock, Dispatcher(), 600)
        self.topic = TopicNamespace().installation_activation
        self.adapter = TranslationMQTTAdapter(self.runtime, self.topic)

    def test_envelope_round_trip_and_validation(self):
        event = installation_activation("person_detector", "active")
        self.assertEqual(SemanticEvent.from_json(event.to_json()), event)
        with self.assertRaises(EventValidationError):
            SemanticEvent.from_json('{"type":"installation.activation"}')
        with self.assertRaises(EventValidationError):
            installation_activation("person_detector", "toggle")

    def test_topics_are_semantic(self):
        self.assertEqual(self.topic, "bwm/installation/activation")
        self.assertEqual(TopicNamespace("venue/bwm").availability("translation"), "venue/bwm/system/status/translation")

    def test_duplicate_cache_is_bounded_and_expires(self):
        now = [0.0]
        cache = RecentEventIds(max_entries=2, ttl_seconds=5, clock=lambda: now[0])
        self.assertFalse(cache.seen("a")); self.assertTrue(cache.seen("a"))
        self.assertFalse(cache.seen("b")); self.assertFalse(cache.seen("c"))
        self.assertFalse(cache.seen("a"))  # LRU eviction
        now[0] = 6
        self.assertFalse(cache.seen("c"))  # TTL expiry

    def test_active_is_idempotent_and_inactive_cancels(self):
        active = installation_activation("person_detector", "active", id="first")
        self.assertTrue(self.adapter.handle(self.topic, active))
        first_engine, started = self.runtime.engine, self.runtime._started_at
        self.clock.advance(100)
        self.assertFalse(self.adapter.handle(self.topic, installation_activation("person_detector", "active", id="second")))
        self.assertIs(self.runtime.engine, first_engine)
        self.assertEqual(self.runtime._started_at, started)
        self.assertFalse(self.adapter.handle(self.topic, active))
        self.assertTrue(self.adapter.handle(self.topic, installation_activation("person_detector", "inactive", id="third")))
        self.assertFalse(self.runtime.is_active)
        self.assertTrue(self.adapter.handle(self.topic, installation_activation("person_detector", "active", id="fourth")))
        self.assertIsNot(self.runtime.engine, first_engine)

    def test_wrong_topic_or_state_never_controls_a_session(self):
        self.assertFalse(self.adapter.handle("bwm/other", installation_activation("person_detector", "active")))
        invalid = SemanticEvent("installation.activation", "person_detector", {"state": "toggle"})
        self.assertFalse(self.adapter.handle(self.topic, invalid))
        self.assertFalse(self.runtime.is_active)

    def test_mqtt_wrapper_uses_qos_one_nonretained_and_rejects_bad_payloads(self):
        fake, delivered = FakeMQTT(), []
        client = SemanticMQTTClient(MQTTSettings(enabled=True, client_id="test"),
                                    lambda topic, event: delivered.append((topic, event)),
                                    client_factory=lambda client_id: fake)
        self.assertTrue(client.start([self.topic]))
        fake.on_connect(fake, None, None, 0)
        self.assertEqual(fake.subscriptions, [(self.topic, 1)])
        self.assertTrue(client.publish(self.topic, installation_activation("person_detector", "active")))
        self.assertFalse(fake.published[0][3])
        message = type("Message", (), {"topic": self.topic,
                                        "payload": installation_activation("person_detector", "active").to_json()})()
        fake.on_message(fake, None, message)
        self.assertEqual(len(delivered), 1)
        message.payload = b"not-json"
        fake.on_message(fake, None, message)
        self.assertEqual(len(delivered), 1)


if __name__ == "__main__":
    unittest.main()
