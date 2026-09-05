import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lighting.halo_runtime import HaloLightingController
from lighting.ola_client import OLAUniverseClient

class Clock:
    def __init__(self): self.value = 0.
    def __call__(self): return self.value
class Ola:
    def __init__(self): self.frames=[]; self.closed=False
    def send(self, frame): self.frames.append(bytes(frame))
    def close(self): self.closed=True
def config(**changes):
    value={"enabled":True,"universe":1,"start_address":1,"frame_interval_seconds":.01,"active_brightness_percent":60,"active_cct_kelvin":2700,"activation_fade_seconds":4,"deactivation_fade_seconds":4,"gesture_cooldown_seconds":7,"whisper_gesture":{"enabled":True,"pulse_count":3,"duration_seconds":7,"target_brightness_percent":50,"target_cct_kelvin":6500}}
    value.update(changes); return value

def test_ola_frame_mapping_activation_gesture_and_cooldown():
    clock, ola = Clock(), Ola(); controller=HaloLightingController(config(), clock=clock, ola_client=ola)
    controller.activate(); assert controller._state_at(0).brightness_percent == 0
    clock.value=4; assert controller._state_at(4).cct_kelvin == 2700
    assert controller.trigger_interaction(); clock.value += 7/6
    state=controller._state_at(clock()); assert state.brightness_percent == pytest.approx(50); assert state.cct_kelvin == pytest.approx(6500)
    assert not controller.trigger_interaction(); clock.value=11; controller.step()
    assert ola.frames[-1][:3] == bytes((153, 0, 0)) # current base: 60%, 2700K, strobe off
    assert len(ola.frames[-1]) == 512

def test_failure_and_disabled_lighting_are_non_fatal_without_serial():
    clock=Clock(); broken=type("Broken",(),{"send":lambda *_: (_ for _ in ()).throw(OSError("olad down")),"close":lambda *_:None})()
    controller=HaloLightingController(config(), clock=clock, ola_client=broken, emit=lambda _:None); controller.activate(); controller.step()
    assert controller._retry_at > 0
    disabled=HaloLightingController(config(enabled=False), clock=clock, ola_client=broken); disabled.activate(); disabled.step()

def test_ola_client_sends_a_full_universe_frame_without_serial_device_access():
    sent=[]
    class Wrapper:
        def Client(self): return self
        def SendDmx(self, universe, frame, callback): sent.append((universe, bytes(frame))); callback(type("Result", (), {"Succeeded": lambda _: True})())
        def AddEvent(self, *_): pass
    output=OLAUniverseClient(1, wrapper_factory=Wrapper, emit=lambda _:None)
    output._wrapper=Wrapper(); output._started=True; output.send(bytes([1,2,0]) + bytes(509)); output._tick()
    assert sent == [(1, bytes([1,2,0]) + bytes(509))]
    assert "serial" not in Path(__file__).resolve().parents[1].joinpath("src/lighting/halo_runtime.py").read_text().lower()
