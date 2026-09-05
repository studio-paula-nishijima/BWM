import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lighting.halo_runtime import HaloLightingController, send_open_dmx_frame
from lighting.open_dmx import BREAK_SECONDS, MARK_AFTER_BREAK_SECONDS


class Clock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value


class Port:
    def __init__(self): self.frames = []; self.closed = False; self.events = []
    @property
    def break_condition(self): return False
    @break_condition.setter
    def break_condition(self, value): self.events.append(("break", value))
    def write(self, frame): self.frames.append(frame); self.events.append(("write", frame))
    def flush(self): self.events.append(("flush",))
    def close(self): self.closed = True


def test_open_dmx_uses_explicit_break_and_mark_timing():
    port = Port()
    send_open_dmx_frame(port, (255, 0, 0), 1,
                        sleep=lambda duration: port.events.append(("sleep", duration)))
    assert port.events[:4] == [
        ("break", True),
        ("sleep", BREAK_SECONDS),
        ("break", False),
        ("sleep", MARK_AFTER_BREAK_SECONDS),
    ]
    assert port.frames[0][:4] == bytes((0, 255, 0, 0))
    assert port.events[-1] == ("flush",)


def config(**overrides):
    result = {"enabled": True, "serial_port": "fake", "frame_interval_seconds": .01,
              "active_brightness_percent": 60, "active_cct_kelvin": 2700,
              "activation_fade_seconds": 4, "deactivation_fade_seconds": 4,
              "gesture_cooldown_seconds": 7,
              "whisper_gesture": {"enabled": True, "pulse_count": 3, "duration_seconds": 7,
                                  "target_brightness_percent": 50, "target_cct_kelvin": 6500}}
    result.update(overrides); return result


def test_activation_fade_gesture_and_cooldown_keep_base_separate():
    clock, port = Clock(), Port()
    controller = HaloLightingController(config(), clock=clock, serial_factory=lambda: port)
    controller.activate()
    assert controller._state_at(0).brightness_percent == 0
    clock.value = 4
    assert controller._state_at(clock()).brightness_percent == 60
    assert controller._state_at(clock()).cct_kelvin == 2700
    assert controller.trigger_interaction() is True
    clock.value += 7 / 6
    pulse = controller._state_at(clock())
    assert pulse.brightness_percent == pytest.approx(50)
    assert pulse.cct_kelvin == pytest.approx(6500)
    assert controller.trigger_interaction() is False
    clock.value = 11
    assert controller._state_at(clock()).brightness_percent == 60
    controller.step()
    assert port.frames and port.frames[-1][3] == 0


def test_dmx_failure_is_isolated_and_disabled_never_opens_port():
    clock = Clock()
    controller = HaloLightingController(config(), clock=clock, serial_factory=lambda: (_ for _ in ()).throw(OSError("gone")), emit=lambda _: None)
    controller.activate(); controller.step()
    assert controller._port is None and controller._retry_at > 0
    disabled = HaloLightingController(config(enabled=False), clock=clock, serial_factory=lambda: (_ for _ in ()).throw(AssertionError()))
    disabled.activate(); disabled.step()
