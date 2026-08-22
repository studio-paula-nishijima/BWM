import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "translation" / "src")]

from live.interaction import OracleInteractionController
from live.oracle_display import DisplayConfig, OracleDisplayController
from live.voice_runtime import VoiceLifecycle, VoiceState
from live.voice_messaging import VoiceStatePublisher


class Coordinator:
    def __init__(self): self.lifecycle, self.completed = VoiceLifecycle(), 0
    def complete_interaction(self, reason): self.completed += 1; return self.lifecycle.set("listening")


class Retrieval:
    def __init__(self, response="river text", error=None): self.queries, self.response, self.error = [], response, error
    def retrieve(self, text):
        self.queries.append(text)
        if self.error: raise self.error
        return {"ok": bool(self.response), "response_text": self.response, "metadata": {}}


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
    def test_empty_asr_skips_retrieval_and_falls_back(self):
        self.controller.on_asr_results([{"status": "ok", "result": {"recognized_text": "  "}}])
        self.assertEqual(self.retrieval.queries, [])
        self.assertEqual(self.coordinator.lifecycle.state, VoiceState.RESPONSE_DISPLAYED)
    def test_display_completion_is_the_only_release_seam(self):
        self.controller.on_asr_results([{"status": "ok", "result": {"recognized_text": "water"}}]); self.wait_for_response()
        self.clock.now = 2; self.controller.poll()
        self.assertEqual(self.coordinator.completed, 1)
        self.assertEqual(self.coordinator.lifecycle.state, VoiceState.LISTENING)
    def test_long_text_scrolls_and_short_text_is_static(self):
        self.assertFalse(self.display.layout("short text")["scrolling"])
        self.assertTrue(self.display.layout("word " * 1000)["scrolling"])


class VoiceMessagingTests(unittest.TestCase):
    def test_shared_voice_state_is_published_only_for_genuine_transition(self):
        class MQTT:
            def __init__(self): self.events = []
            def publish(self, topic, event): self.events.append((topic, event)); return True
        mqtt, lifecycle = MQTT(), VoiceLifecycle()
        lifecycle.add_transition_observer(VoiceStatePublisher(mqtt, emit=lambda _: None).publish_transition)
        lifecycle.set("listening"); lifecycle.set("listening")
        self.assertEqual(len(mqtt.events), 1)
        self.assertEqual(mqtt.events[0][0], "bwm/voice/state")
        self.assertEqual(mqtt.events[0][1].payload, {"state": "listening"})


if __name__ == "__main__": unittest.main()
