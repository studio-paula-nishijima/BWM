import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "translation" / "src"))

from runtime.clock import SimulatedClock
from runtime.mqtt_adapter import TranslationSemanticIngress
from runtime.session import PlaybackSessionRuntime
from shared.messaging.ble import BLEFragmentReassembler, BLESettings, SemanticBLETransport, END, START
from shared.messaging.events import installation_activation
from shared.messaging.topics import TopicNamespace


def frame(flags, sequence, body):
    return bytes([flags, sequence & 255, sequence >> 8]) + body


class FragmentTests(unittest.TestCase):
    def test_single_and_multiple_frames(self):
        body = b'{"version":1}'
        r = BLEFragmentReassembler()
        self.assertEqual(r.feed(frame(START | END, 0, body)), body)
        self.assertIsNone(r.feed(frame(START, 0, body[:5])))
        self.assertEqual(r.feed(frame(END, 1, body[5:])), body)

    def test_bad_order_and_malformed_data_reset_for_next_event(self):
        r = BLEFragmentReassembler()
        with self.assertRaisesRegex(ValueError, "before start"):
            r.feed(frame(0, 0, b"x"))
        self.assertIsNone(r.feed(frame(START, 0, b"first")))
        with self.assertRaisesRegex(ValueError, "sequence gap"):
            r.feed(frame(END, 2, b"bad"))
        self.assertEqual(r.feed(frame(START | END, 0, b"good")), b"good")
        with self.assertRaisesRegex(ValueError, "start frame"):
            r.feed(frame(START, 3, b"bad"))
        with self.assertRaisesRegex(ValueError, "exceeds"):
            BLEFragmentReassembler(64).feed(frame(START | END, 0, b"x" * 65))


class Dispatcher:
    def dispatch(self, event):
        pass


class BLEIngressTests(unittest.TestCase):
    def setUp(self):
        self.clock = SimulatedClock()
        self.sessions = [[{"playback_time": 0, "target": "one"}], [{"playback_time": 0, "target": "two"}]]
        self.runtime = PlaybackSessionRuntime(lambda: self.sessions.pop(0), self.clock, Dispatcher(), 600)
        self.ingress = TranslationSemanticIngress(self.runtime, TopicNamespace().installation_activation)
        self.received = []
        self.transport = SemanticBLETransport(BLESettings(enabled=True), self._deliver)

    def _deliver(self, event):
        self.received.append(event); return self.ingress.handle_event(event)

    def _notify(self, raw):
        self.transport.notification(None, bytearray(frame(START | END, 0, raw)))

    def test_complete_event_uses_transport_neutral_ingress_and_active_is_idempotent(self):
        event = installation_activation("person_detector", "active", id="ble-one")
        self._notify(event.to_json().encode())
        engine, started = self.runtime.engine, self.runtime._started_at
        self.clock.advance(10)
        self._notify(installation_activation("person_detector", "active", id="ble-two").to_json().encode())
        self.assertTrue(self.runtime.is_active)
        self.assertIs(self.runtime.engine, engine)
        self.assertEqual(self.runtime._started_at, started)
        self.assertEqual([item.id for item in self.received], ["ble-one", "ble-two"])

    def test_idle_event_starts_and_cross_transport_ids_deduplicate_in_both_orders(self):
        event = installation_activation("person_detector", "active", id="same")
        self._notify(event.to_json().encode())
        self.assertFalse(self.ingress.handle(TopicNamespace().installation_activation, event))
        self.assertTrue(self.runtime.is_active)
        self.runtime.deactivate()
        event2 = installation_activation("person_detector", "active", id="other")
        self.assertTrue(self.ingress.handle(TopicNamespace().installation_activation, event2))
        self.transport.notification(None, bytearray(frame(START | END, 0, event2.to_json().encode())))
        self.assertEqual([item.id for item in self.received], ["same", "other"])

    def test_malformed_utf8_json_and_disconnect_never_create_inactive(self):
        self._notify(b"\xff")
        self._notify(b"not-json")
        self.transport._reassembler.feed(frame(START, 0, b"unfinished"))
        self.transport._reassembler.reset()  # models disconnect; it is not an event
        self.assertFalse(self.runtime.is_active)
        self._notify(installation_activation("person_detector", "active", id="after-bad").to_json().encode())
        self.assertTrue(self.runtime.is_active)

    def test_contract_diagnostics_are_preserved(self):
        raw = (b'{"version":1,"id":"diagnostic","type":"installation.activation",'
               b'"origin":"person_detector","timestamp":"2026-08-28T12:00:00Z",'
               b'"payload":{"state":"active"},"diagnostics":{"trigger_source":"camera_confirmation"}}')
        self._notify(raw)
        self.assertEqual(self.received[0].diagnostics["trigger_source"], "camera_confirmation")

    def test_disabled_transport_does_not_start(self):
        self.assertFalse(SemanticBLETransport(BLESettings(), self._deliver).start())

    def test_fake_client_reconnects_and_resubscribes(self):
        transport = SemanticBLETransport(BLESettings(enabled=True, reconnect_seconds=.001), self._deliver)
        device = type("Device", (), {"name": "BWM Vision"})()

        class Scanner:
            calls = 0
            @classmethod
            async def find_device_by_filter(cls, predicate, timeout):
                cls.calls += 1
                if cls.calls == 3:
                    transport._stop.set()
                    return None
                return device

        class Client:
            clients = []
            def __init__(self, _device): self.is_connected = False; self.subscribed = None; Client.clients.append(self)
            async def connect(self): self.is_connected = True
            async def start_notify(self, characteristic, callback):
                self.subscribed = (characteristic, callback); self.is_connected = False
            async def disconnect(self): self.is_connected = False

        transport._scanner, transport._client_factory = Scanner, Client
        asyncio.run(transport._run())
        self.assertEqual(Scanner.calls, 3)
        self.assertEqual(len(Client.clients), 2)
        self.assertTrue(all(client.subscribed[0] == transport.settings.characteristic_uuid for client in Client.clients))


if __name__ == "__main__":
    unittest.main()
