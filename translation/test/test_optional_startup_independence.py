import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "translation" / "src"))

from play_events import start_optional_initializers
from lighting.halo_runtime import HaloLightingController
from runtime.clock import SimulatedClock
from runtime.session import PlaybackSessionRuntime


class Dispatcher:
    def __init__(self):
        self.events = []

    def begin_session(self):
        pass

    def dispatch(self, event):
        self.events.append(event)

    def is_idle(self):
        return True


class Lighting:
    activation_delay_seconds = 4.0

    def __init__(self):
        self.steps = 0

    def activate(self):
        pass

    def step(self):
        self.steps += 1

    def deactivate_async(self):
        pass


def test_slow_and_failed_optional_startup_do_not_delay_core_admission():
    clock, dispatcher, lighting = SimulatedClock(), Dispatcher(), Lighting()
    runtime = PlaybackSessionRuntime(
        lambda: [{"type": "solenoid", "target": "one", "duration": 0.1, "playback_time": 0}],
        clock, dispatcher, 60, initially_active=True, lighting_controller=lighting,
    )
    slow_started, release_slow, fast_finished = threading.Event(), threading.Event(), threading.Event()
    messages = []

    def delayed_for_twenty_session_seconds():
        slow_started.set()
        release_slow.wait()

    def failed_outright():
        raise RuntimeError("optional adapter failed")

    threads = start_optional_initializers((
        ("SLOW", delayed_for_twenty_session_seconds),
        ("FAILED", failed_outright),
        ("FAST", fast_finished.set),
    ), emit=messages.append)

    assert slow_started.wait(1)
    assert fast_finished.wait(1)
    threads[1].join(timeout=1)
    for _ in range(3):
        clock.advance(1)
        runtime.step()
        assert dispatcher.events == []
    clock.advance(1)
    runtime.step()
    assert [event["target"] for event in dispatcher.events] == ["one"]
    assert lighting.steps >= 5  # activation plus every simulated startup second
    assert threads[0].is_alive()
    assert any("optional adapter failed" in message for message in messages)

    # The optional operation remains incomplete for the equivalent of twenty
    # session seconds; core admission already occurred at the four-second mark.
    clock.advance(16)
    assert threads[0].is_alive()
    release_slow.set()
    for thread in threads:
        thread.join(timeout=1)


def test_ola_failure_does_not_gate_four_second_solenoid_deadline():
    class FailedOla:
        def send(self, _frame):
            raise OSError("olad unavailable")

        def close(self):
            pass

    clock, dispatcher = SimulatedClock(), Dispatcher()
    lighting = HaloLightingController({
        "enabled": True,
        "activation_fade_seconds": 4,
        "active_brightness_percent": 60,
        "active_cct_kelvin": 2700,
        "retry_seconds": 5,
    }, clock=clock.now, ola_client=FailedOla(), emit=lambda _message: None)
    runtime = PlaybackSessionRuntime(
        lambda: [{"type": "solenoid", "target": "one", "duration": 0.1, "playback_time": 0}],
        clock, dispatcher, 60, initially_active=True, lighting_controller=lighting,
    )

    clock.advance(4)
    runtime.step()

    assert [event["target"] for event in dispatcher.events] == ["one"]
