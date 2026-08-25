import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "translation" / "src"))

from live.semantic_ingress import VoiceSemanticIngress
from runtime.mqtt_adapter import TranslationSemanticIngress
from shared.messaging.events import SemanticEvent, installation_activation, voice_state
from shared.messaging.uart import (NewlineEventDecoder, UARTConfigurationError,
                                   assert_uart_unclaimed, encode_frame, resolve_uart0_device)


class UARTFramingTests(unittest.TestCase):
    def test_frames_partial_multiple_bad_and_recovery(self):
        first, second = voice_state("voice_pi", "listening", id="one"), installation_activation("pi", "active", id="two")
        decoder = NewlineEventDecoder(256)
        self.assertEqual(decoder.feed(encode_frame(first)[:11]), [])
        self.assertEqual(decoder.feed(encode_frame(first)[11:] + encode_frame(second)), [first, second])
        self.assertEqual(decoder.feed(b"not json\n" + encode_frame(first)), [first])
        self.assertEqual(decoder.feed(b"x" * 257 + b"\n" + encode_frame(second)), [second])
        with self.assertRaises(ValueError): encode_frame(first, 10)

    def test_invalid_envelope_is_rejected(self):
        decoder = NewlineEventDecoder(256)
        self.assertEqual(decoder.feed(b'{"type":"voice.state"}\n'), [])


class ResolverTests(unittest.TestCase):
    def test_uart0_maps_to_concrete_tty_without_serial0(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); dt, tty = root / "dt", root / "tty"
            (dt / "aliases").mkdir(parents=True); (dt / "soc" / "uart@0").mkdir(parents=True)
            (dt / "aliases" / "uart0").write_bytes(b"/soc/uart@0\0")
            node = tty / "ttyAMA0" / "device"; node.mkdir(parents=True)
            (node / "of_node").mkdir()
            expected, of_node = dt / "soc" / "uart@0", node / "of_node"
            self.assertEqual(resolve_uart0_device(dt, tty, path_resolver=lambda path: expected if path == of_node else path.resolve(strict=True)), "/dev/ttyAMA0")
        with self.assertRaises(UARTConfigurationError): resolve_uart0_device(Path("missing"), Path("missing"))

    def test_ownership_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            cmdline = Path(temp) / "cmdline"; cmdline.write_text("console=ttyAMA0,115200")
            with self.assertRaises(UARTConfigurationError):
                assert_uart_unclaimed("/dev/ttyAMA0", cmdline_path=cmdline, systemctl=lambda *_args, **_kwargs: type("R", (), {"returncode": 1})())
            cmdline.write_text("quiet")
            assert_uart_unclaimed("/dev/ttyAMA0", cmdline_path=cmdline, systemctl=lambda *_args, **_kwargs: type("R", (), {"returncode": 1})())
            with self.assertRaises(UARTConfigurationError):
                assert_uart_unclaimed("/dev/ttyAMA0", cmdline_path=cmdline, systemctl=lambda *_args, **_kwargs: type("R", (), {"returncode": 0})())


class IngressTests(unittest.TestCase):
    def test_voice_activation_seam_is_transport_neutral_and_deduplicated(self):
        delivered = []; ingress = VoiceSemanticIngress(lambda state, event: delivered.append((state, event.id)))
        event = installation_activation("translation_pi", "active", id="same")
        self.assertTrue(ingress.handle_event(event)); self.assertFalse(ingress.handle_event(event))
        self.assertEqual(delivered, [("active", "same")])

    def test_translation_deduplicates_across_transport_entrypoints(self):
        class Runtime:
            def __init__(self): self.calls = 0
            def activate(self): self.calls += 1; return True
            def deactivate(self): return False
        runtime = Runtime(); ingress = TranslationSemanticIngress(runtime, "activation", "voice")
        event = installation_activation("voice_pi", "active", id="same")
        self.assertTrue(ingress.handle("activation", event)); self.assertFalse(ingress.handle_event(event))
        self.assertEqual(runtime.calls, 1)
