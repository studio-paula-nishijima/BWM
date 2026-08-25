import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "translation" / "src")]

from live.interaction import OracleInteractionController, compact_preview, retrieval_debug_line
from live.oracle_display import DisplayConfig, OracleDisplayController
from live.voice_runtime import VoiceLifecycle, VoiceState
from live.voice_messaging import VoiceStatePublisher


class Coordinator:
    def __init__(self): self.lifecycle, self.completed = VoiceLifecycle(), 0
    def complete_interaction(self, reason): self.completed += 1; return self.lifecycle.set("listening")


class Retrieval:
    def __init__(self, response="river text", error=None): self.queries, self.response, self.error, self.items = [], response, error, []
    def retrieve(self, text):
        self.queries.append(text)
        if self.error: raise self.error
        return {"ok": bool(self.response), "response_text": self.response, "metadata": {}}
    def submit(self, text):
        try: self.items.append({"ok": True, "result": self.retrieve(text)})
        except Exception as exc: self.items.append({"ok": False, "error": str(exc)})
        return "1", "accepted"
    def poll(self): items, self.items = self.items, []; return items
    def fallback_response(self, reason):
        self.fallback_reason = reason
        return {"ok": True, "response_text": "configured River Culture response", "metadata": {"fallback": True}}
    def shutdown(self): pass


class Clock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now


class Stage3UInteractionTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.coordinator, self.retrieval = Clock(), Coordinator(), Retrieval()
        self.display = OracleDisplayController(DisplayConfig(minimum_response_seconds=1), clock=self.clock)
        self.controller = OracleInteractionController(self.coordinator, self.retrieval, self.display, emit=lambda _: None)
        self.coordinator.lifecycle.set("capture_processing")

    def tearDown(self): self.controller.close()
    def wait_for_response(self):
        for _ in range(100):
            self.controller.poll()
            if self.coordinator.lifecycle.state is VoiceState.RESPONSE_DISPLAYED: return
            time.sleep(.01)
        self.fail("retrieval did not complete")
    def test_raw_nonempty_asr_text_reaches_retrieval_once_and_response_is_opaque(self):
        self.controller.on_asr_results([{"status": "ok", "result": {"recognized_text": "fragment water"}}])
        self.wait_for_response()
        self.assertEqual(self.retrieval.queries, ["fragment water"])
        self.assertEqual(self.display.response_text, "river text")
        self.assertEqual(self.coordinator.completed, 0)
    def test_empty_asr_uses_retrieval_owned_fallback(self):
        self.controller.on_asr_results([{"status": "ok", "result": {"recognized_text": "  "}}])
        self.wait_for_response()
        self.assertEqual(self.retrieval.queries, [])
        self.assertEqual(self.retrieval.fallback_reason, "empty_asr")
        self.assertEqual(self.display.response_text, "configured River Culture response")
    def test_display_completion_is_the_only_release_seam(self):
        self.controller.on_asr_results([{"status": "ok", "result": {"recognized_text": "water"}}]); self.wait_for_response()
        self.clock.now = 2; self.controller.poll()
        self.assertEqual(self.coordinator.completed, 1)
        self.assertEqual(self.coordinator.lifecycle.state, VoiceState.LISTENING)
    def test_long_text_scrolls_and_short_text_is_static(self):
        self.assertFalse(self.display.layout("short text")["scrolling"])
        self.assertTrue(self.display.layout("word " * 1000)["scrolling"])

    def test_demo_display_cap_preserves_full_text(self):
        display = OracleDisplayController(DisplayConfig(minimum_response_seconds=2, max_response_seconds=8), clock=self.clock)
        text = "word " * 1000
        self.assertEqual(display.layout(text)["duration"], 8)
        display.show_response(text)
        self.assertEqual(display.response_text, text)


class VoiceMessagingTests(unittest.TestCase):
    def test_shared_voice_state_is_published_only_for_genuine_transition(self):
        class MQTT:
            def __init__(self): self.events = []
            def publish(self, topic, event): self.events.append((topic, event)); return True
        mqtt, lifecycle = MQTT(), VoiceLifecycle()
        lifecycle.add_transition_observer(VoiceStatePublisher(mqtt, emit=lambda _: None).publish_transition)
        lifecycle.set("initializing"); lifecycle.set("initializing"); lifecycle.set("listening")
        self.assertEqual(len(mqtt.events), 2)
        self.assertEqual(mqtt.events[0][0], "bwm/voice/state")
        self.assertEqual(mqtt.events[0][1].payload, {"state": "initializing"})

    def test_voice_state_fanout_preserves_one_event_identity(self):
        class MQTT:
            def __init__(self): self.events = []
            def publish(self, topic, event): self.events.append((topic, event)); return True
        class UART:
            def __init__(self): self.events = []
            def send(self, event): self.events.append(event); return True
        mqtt, uart = MQTT(), UART()
        VoiceStatePublisher(mqtt, uart_transport=uart, emit=lambda _: None).publish_transition(None, VoiceState.LISTENING)
        self.assertEqual(uart.events[0], mqtt.events[0][1])

    def test_fanout_keeps_one_envelope_when_one_transport_fails(self):
        class MQTT:
            def __init__(self): self.events = []
            def publish(self, topic, event): self.events.append((topic, event)); return False
        class UART:
            def __init__(self): self.events = []
            def send(self, event): self.events.append(event); return True
        emitted, mqtt, uart = [], MQTT(), UART()
        VoiceStatePublisher(mqtt, uart_transport=uart, emit=emitted.append).publish_transition(None, VoiceState.CAPTURE_PROCESSING)
        mqtt_event, uart_event = mqtt.events[0][1], uart.events[0]
        self.assertEqual(mqtt_event.to_dict(), uart_event.to_dict())
        self.assertTrue(any("failed via MQTT" in line for line in emitted))
        self.assertTrue(any("sent via UART" in line for line in emitted))

    def test_all_transport_failures_are_observable_but_do_not_raise(self):
        class Unavailable:
            def publish(self, *_): return False
            def send(self, *_): return False
        emitted = []
        VoiceStatePublisher(Unavailable(), uart_transport=Unavailable(), emit=emitted.append).publish_transition(
            None, VoiceState.CAPTURE_PROCESSING)
        self.assertTrue(any("all state transports unavailable" in line for line in emitted))

    def test_initializing_is_not_admissible_and_has_a_view(self):
        lifecycle = VoiceLifecycle(); lifecycle.set("initializing")
        self.assertEqual(lifecycle.state, VoiceState.INITIALIZING)
        display = OracleDisplayController(); display.show_initializing()
        self.assertEqual(display.view, "initializing")


class RetrievalDebugTests(unittest.TestCase):
    def result(self, text, **chunk):
        return {"metadata": {"raw_results": [{"text": text, **chunk}]}}
    def test_long_chunk_is_compact_with_book_page(self):
        text = "a" * 60 + "b" * 60
        self.assertEqual(retrieval_debug_line(self.result(text, printed_pages=[237])),
                         f'[Retrieval] book page 237 | chunk: "{"a" * 50} ... {"b" * 50}"')
    def test_short_and_multiline_chunk_is_once_and_single_line(self):
        self.assertEqual(retrieval_debug_line(self.result("river\n carries water")),
                         '[Retrieval] chunk: "river carries water"')
    def test_pdf_and_page_range_are_labeled_without_failure_when_absent(self):
        self.assertIn("PDF page 251", retrieval_debug_line(self.result("x", pdf_pages=[251])))
        self.assertIn("book pages 237–238", retrieval_debug_line(self.result("x", printed_pages=[237, 238])))
        self.assertEqual(retrieval_debug_line(self.result("x")), '[Retrieval] chunk: "x"')
    def test_response_preview_is_compact_without_changing_source(self):
        text = "a" * 60 + "b" * 60
        self.assertEqual(compact_preview(text), "a" * 50 + " ... " + "b" * 50)


if __name__ == "__main__": unittest.main()
