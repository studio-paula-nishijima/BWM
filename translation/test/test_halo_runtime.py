import sys
import subprocess
import time
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
    assert len(ola.frames[-1]) == 3

def test_failure_and_disabled_lighting_are_non_fatal_without_serial():
    clock=Clock(); broken=type("Broken",(),{"send":lambda *_: (_ for _ in ()).throw(OSError("olad down")),"close":lambda *_:None})()
    controller=HaloLightingController(config(), clock=clock, ola_client=broken, emit=lambda _:None); controller.activate(); controller.step()
    assert controller._retry_at > 0
    disabled=HaloLightingController(config(enabled=False), clock=clock, ola_client=broken); disabled.activate(); disabled.step()

def test_ola_client_keeps_one_packaged_cli_source_and_blackouts_on_close():
    class Stdin:
        def __init__(self): self.writes=[]; self.closed=False
        def write(self, value): self.writes.append(value); return len(value)
        def flush(self): pass
        def close(self): self.closed=True
    class Process:
        def __init__(self): self.stdin=Stdin(); self.returncode=None; self.terminated=False; self.waited=False
        def poll(self): return self.returncode
        def terminate(self): self.terminated=True; self.returncode=0
        def wait(self, timeout=None):
            self.waited=True
            if self.stdin.closed: self.returncode=0
            return self.returncode
        def kill(self): self.returncode=-9
    processes=[]
    one_shots=[]
    def popen(args, **kwargs):
        processes.append((args, kwargs, Process()))
        return processes[-1][2]
    def run(args, **kwargs):
        one_shots.append((args, kwargs))
        return type("Result", (), {"returncode": 0})()

    output=OLAUniverseClient(1, refresh_hz=200, popen_factory=popen,
                             run_factory=run, emit=lambda _:None)
    output.send(bytes([1,2,0]))
    deadline=time.monotonic()+.5
    while not processes or not processes[0][2].stdin.writes:
        assert time.monotonic() < deadline
        time.sleep(.005)
    output.send(bytes([3,4,0]))
    deadline=time.monotonic()+.5
    while not any(line == b"3,4,0\n" for line in processes[0][2].stdin.writes):
        assert time.monotonic() < deadline
        time.sleep(.005)
    output.close()

    assert len(processes) == 1
    assert processes[0][0] == ["ola_streaming_client", "-u", "1"]
    assert len(processes[0][2].stdin.writes[-1].decode().strip().split(",")) == 3
    assert set(processes[0][2].stdin.writes[-1].decode().strip().split(",")) == {"0"}
    assert processes[0][2].waited
    assert not processes[0][2].terminated
    assert one_shots[0][0] == ["ola_streaming_client", "-u", "1", "-d", "0,0,0"]
    assert one_shots[0][1]["timeout"] == 1.0
    source=Path(__file__).resolve().parents[1].joinpath("src/lighting/halo_runtime.py").read_text().lower()
    assert "pyserial" not in source and "/dev/ttyusb" not in source


def test_ola_client_rejects_empty_or_oversized_frames():
    output=OLAUniverseClient(1, popen_factory=lambda *_args, **_kwargs: None)
    with pytest.raises(ValueError): output.send(b"")
    with pytest.raises(ValueError): output.send(bytes(513))


def test_ola_client_forces_exit_only_after_graceful_drain_times_out():
    class Stdin:
        def close(self): pass
    class StuckProcess:
        def __init__(self): self.stdin=Stdin(); self.returncode=None; self.terminated=False
        def poll(self): return self.returncode
        def wait(self, timeout=None):
            if not self.terminated: raise subprocess.TimeoutExpired("ola_streaming_client", timeout)
            return self.returncode
        def terminate(self): self.terminated=True; self.returncode=0
        def kill(self): self.returncode=-9
    process=StuckProcess()
    OLAUniverseClient._close_process(process)
    assert process.terminated and process.returncode == 0


def test_ola_one_shot_blackout_failure_is_non_fatal():
    def fail(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ola_streaming_client", 1)
    messages=[]
    output=OLAUniverseClient(1, run_factory=fail, emit=messages.append)
    output._frame[:]=bytes((1, 2, 0))
    output.close()
    assert messages and "continuing shutdown" in messages[0]


def test_provisioning_matches_rpi05_and_resolves_dynamic_ola_id_by_serial():
    root=Path(__file__).resolve().parents[1]
    script=root.joinpath("scripts/configure-ola-halo.sh").read_text()
    runtime=root.joinpath("configs/runtime.yaml").read_text()
    docs=root.joinpath("tools/README_halo_ola.md").read_text()
    assert "config_dir=${OLA_CONFIG_DIR:-/etc/ola}" in script
    assert "/var/lib/ola" not in script
    assert 'ola-usbserial.conf" enabled false' in script
    assert 'awk -v serial="$adapter_serial"' in script
    assert 'ola_patch -d "$1" -p "$2" -u "$universe"' in script
    assert "adapter_serial: BG03CXL2" in runtime
    assert "ola-python" not in docs
