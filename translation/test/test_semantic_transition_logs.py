import sys
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "translation" / "src"))

from live.semantic_ingress import VoiceSemanticIngress
from runtime.activation_publication import TranslationActivationPublisher
from runtime.mqtt_adapter import TranslationSemanticIngress
from shared.messaging.events import installation_activation, whisper_state
from shared.messaging.topics import TopicNamespace


class UART:
    def send(self, _event):
        return True


class SemanticTransitionLogTests(unittest.TestCase):
    def test_translation_activation_publication_uses_semantic_tx_label(self):
        emitted = []
        self.assertTrue(TranslationActivationPublisher(UART(), emit=emitted.append).publish("inactive"))
        self.assertRegex(emitted[0], r"^\[SemanticTx\] transport=uart type=installation\.activation origin=translation_pi state=inactive id=.* result=sent$")

    def test_accepted_translation_activation_uses_semantic_rx_label(self):
        emitted, delivered = [], []
        ingress = VoiceSemanticIngress(lambda state, event: delivered.append((state, event.id)), emit=emitted.append)
        self.assertTrue(ingress.handle_event(installation_activation("translation_pi", "inactive", id="e7c"), transport="uart"))
        self.assertEqual(emitted, ["[SemanticRx] transport=uart type=installation.activation origin=translation_pi state=inactive id=e7c"])
        self.assertEqual(delivered, [("inactive", "e7c")])

    def test_translation_records_received_voice_lifecycle_with_semantic_rx_label(self):
        class Runtime:
            def observe_whisper_state(self, state):
                return state

        emitted = []
        ingress = TranslationSemanticIngress(Runtime(), TopicNamespace().installation_activation,
                                             TopicNamespace().whisper_state)
        with unittest.mock.patch("builtins.print", emitted.append):
            self.assertEqual(ingress.handle_event(whisper_state("whisper_pi", "listening", id="voice-1"),
                                                  transport="uart"), "listening")
        self.assertEqual(emitted, ["[SemanticRx] transport=uart type=whisper.state origin=whisper_pi state=listening id=voice-1"])


if __name__ == "__main__":
    unittest.main()
