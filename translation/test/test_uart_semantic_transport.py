import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "translation" / "src"))

from live.semantic_ingress import VoiceSemanticIngress
from runtime.mqtt_adapter import TranslationSemanticIngress
from shared.messaging.events import SemanticEvent, installation_activation, whisper_state
from shared.messaging.uart import (NewlineEventDecoder, SemanticUARTTransport,
                                   UARTConfigurationError, UARTSettings,
                                   assert_uart_unclaimed, encode_frame,
                                   resolve_uart0_device)


class UARTFramingTests(unittest.TestCase):
    def setUp(self):
        self.first = whisper_state("whisper_pi", "listening", id="one")
        self.second = installation_activation("pi", "active", id="two")

    def test_utf8_frame_round_trip(self):
        decoder = NewlineEventDecoder(256)
        self.assertEqual(decoder.feed(encode_frame(self.first)), [self.first])

    def test_partial_and_multiple_frames(self):
        decoder = NewlineEventDecoder(256)
        first_frame = encode_frame(self.first)
        self.assertEqual(decoder.feed(first_frame[:11]), [])
        self.assertEqual(decoder.feed(first_frame[11:] + encode_frame(self.second)),
                         [self.first, self.second])

    def test_invalid_utf8_then_valid_frame_in_one_feed(self):
        decoder = NewlineEventDecoder(256)
        with self.assertLogs("shared.messaging.uart", level="WARNING") as logs:
            events = decoder.feed(b"\xff\xfe\xfa\n" + encode_frame(self.first))
        self.assertEqual(events, [self.first])
        self.assertIn("Rejected malformed UART frame", logs.output[0])
        self.assertNotIn("\\xff", logs.output[0])

    def test_utf32_style_corruption_then_valid_frame_across_feeds(self):
        decoder = NewlineEventDecoder(256)
        self.assertEqual(decoder.feed(b"\x00\x00\x00{\x00\x11\x00\x00"), [])
        self.assertEqual(decoder.feed(b"\n"), [])
        self.assertEqual(decoder.feed(encode_frame(self.second)), [self.second])

    def test_crlf_is_accepted(self):
        decoder = NewlineEventDecoder(256)
        frame = encode_frame(self.first).removesuffix(b"\n") + b"\r\n"
        self.assertEqual(decoder.feed(frame), [self.first])

    def test_oversized_frame_discards_until_newline_then_recovers(self):
        decoder = NewlineEventDecoder(256)
        self.assertEqual(decoder.feed(b"x" * 257 + b"ignored\n" + encode_frame(self.second)),
                         [self.second])

    def test_encode_rejects_oversized_frame(self):
        with self.assertRaises(ValueError):
            encode_frame(self.first, 10)

    def test_invalid_envelope_is_rejected(self):
        decoder = NewlineEventDecoder(256)
        self.assertEqual(decoder.feed(b'{"type":"whisper.state"}\n'), [])


class UARTReaderTests(unittest.TestCase):
    def _transport(self, serial, delivered):
        transport = SemanticUARTTransport(
            UARTSettings(enabled=True, device_mode="explicit", device="COM1"),
            delivered.append,
        )
        transport._serial = serial
        return transport

    def test_reader_survives_malformed_frame_and_delivers_next_event(self):
        expected = whisper_state("whisper_pi", "listening", id="after-garbage")
        delivered = []

        class Serial:
            def __init__(self):
                self.chunks = [b"\xff\xfe\xfa\n", encode_frame(expected)]

            def read(self, _size):
                if self.chunks:
                    return self.chunks.pop(0)
                transport._stop.set()
                return b""

        serial = Serial()
        transport = self._transport(serial, delivered)
        transport._read_loop()
        self.assertEqual(delivered, [expected])

    def test_reader_still_terminates_on_serial_read_failure(self):
        class Serial:
            calls = 0

            def read(self, _size):
                self.calls += 1
                raise OSError("device disappeared")

        serial = Serial()
        transport = self._transport(serial, [])
        with self.assertLogs("shared.messaging.uart", level="WARNING") as logs:
            transport._read_loop()
        self.assertEqual(serial.calls, 1)
        self.assertTrue(any("UART read failed; transport is degraded" in line
                            for line in logs.output))


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
        event = installation_activation("whisper_pi", "active", id="same")
        self.assertTrue(ingress.handle("activation", event)); self.assertFalse(ingress.handle_event(event))
        self.assertEqual(runtime.calls, 1)
