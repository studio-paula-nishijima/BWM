import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from actuation.servo_controller import ServoActuationController
from live.voice_messaging import VoiceInteractionPublisher
from shared.messaging.events import EventValidationError, voice_interaction
from whisper.models import WhisperDetectionResult
from whisper.profiles import TemporalProfilePolicy


class FakeServo:
    def go_home(self): pass
    def shutdown(self): pass


def test_detector_payload_requires_value_but_button_is_value_free():
    assert voice_interaction("voice", "detector", silero_selection_value=.006).payload == {"source": "detector", "silero_selection_value": .006}
    assert voice_interaction("voice", "button").payload == {"source": "button"}
    with pytest.raises(EventValidationError): voice_interaction("voice", "button", silero_selection_value=0)


def test_servo_explicit_sequence_preserves_random_button_path():
    controller = ServoActuationController({"channel": 0, "frequency": 50, "home_pulse": 1500, "min_pulse": 1000,
                                           "max_pulse": 2000, "cooldown_seconds": 0}, servo_factory=lambda **_: FakeServo(), random_choice=lambda _: 5)
    controller._run_sequence = lambda sequence: None
    assert controller.actuate(sequence=2)["sequence"] == 2
    controller._busy = False
    assert controller.actuate()["sequence"] == 5


def test_one_interaction_envelope_is_reused_across_transports():
    sent = []
    mqtt = type("MQTT", (), {"publish": lambda _, topic, event: sent.append((topic, event)) or True})()
    uart = type("UART", (), {"send": lambda _, event: sent.append(("uart", event)) or True})()
    event = VoiceInteractionPublisher(mqtt, uart_transport=uart, emit=lambda _: None).publish("detector", .02)
    assert len(sent) == 2 and sent[0][1] is event and sent[1][1] is event


def test_selector_latches_even_median_of_final_ten_qualifying_frames():
    policy = TemporalProfilePolicy("temporal_only", {"fallback_confirmation_frames": 10})
    values = [.001, .002, .003, .004, .005, .006, .007, .008, .009, .010]
    decision = None
    for index, value in enumerate(values, 1):
        result = WhisperDetectionResult(temporal_v1_raw_is_whisper=True, temporal_v1_qualifying_run=index,
                                        silero_probability=value)
        decision = policy.update(result)
    assert decision.trigger and decision.silero_selection_value == pytest.approx(.0055)
    # The policy emits one crossing only; later qualifying frames cannot revise it.
    assert not policy.update(WhisperDetectionResult(temporal_v1_raw_is_whisper=True,
                                                     temporal_v1_qualifying_run=11,
                                                     silero_probability=.9)).trigger
