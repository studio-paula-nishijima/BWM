import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from lighting.halo_runtime import HaloLightingController
from lighting.runoff_activity import (
    RunoffActivityTimeline,
    SessionRunoffActivity,
    mean_runoff_activity,
)
from play_events import PreparedSessionData, parse_args, prepare_events_with_origin
from runtime.clock import SimulatedClock
from runtime.gpio_backend import NoActuationBackend
from runtime.router import EventRouter
from runtime.session import PlaybackSessionRuntime


class Ola:
    def send(self, _frame):
        pass

    def close(self):
        pass


def lighting_config(**runoff_changes):
    runoff = {
        "enabled": True,
        "min_brightness": 0.50,
        "max_brightness": 0.70,
        "smoothing_seconds": 5.0,
    }
    runoff.update(runoff_changes)
    return {
        "enabled": True,
        "active_brightness_percent": 60,
        "active_cct_kelvin": 2700,
        "activation_fade_seconds": 0,
        "deactivation_fade_seconds": 4,
        "frame_interval_seconds": 0.01,
        "runoff_brightness": runoff,
        "whisper_gesture": {
            "enabled": True,
            "pulse_count": 3,
            "duration_seconds": 7,
            "target_brightness_percent": 50,
            "target_cct_kelvin": 6500,
        },
        "gesture_cooldown_seconds": 7,
    }


def controller_at(activity):
    clock = SimulatedClock()
    controller = HaloLightingController(lighting_config(), clock=clock.now, ola_client=Ola())
    controller.set_runoff_activity(activity)
    controller.activate()
    controller.step()
    return clock, controller


def test_six_channel_arithmetic_mean_uses_normalized_shaped_values():
    values = {f"solenoid_{index}": np.array([index / 10, 1 - index / 10]) for index in range(1, 7)}
    assert mean_runoff_activity(values) == pytest.approx([0.35, 0.65])


@pytest.mark.parametrize("activity, expected", [(0.0, 50.0), (1.0, 70.0), (0.5, 60.0)])
def test_linear_activity_mapping(activity, expected):
    _, controller = controller_at(activity)
    assert controller.base.brightness_percent == pytest.approx(expected)
    assert controller.base.cct_kelvin == 2700


def test_wall_clock_smoothing_prevents_steps_and_sustained_peak_becomes_bright():
    clock, controller = controller_at(0.0)
    controller.set_runoff_activity(1.0)
    assert controller._state_at(clock.now()).brightness_percent == 50
    clock.advance(5)
    assert controller._state_at(clock.now()).brightness_percent == pytest.approx(62.6424, abs=0.001)
    clock.advance(25)
    assert controller._state_at(clock.now()).brightness_percent > 69.9


def test_repeated_short_changes_cannot_create_strobe_like_brightness_steps():
    clock, controller = controller_at(0.0)
    samples = [controller.base.brightness_percent]
    for index in range(30):
        controller.set_runoff_activity(float(index % 2))
        clock.advance(0.1)
        samples.append(controller._state_at(clock.now()).brightness_percent)
    assert max(abs(after - before) for before, after in zip(samples, samples[1:])) < 0.4


def test_mutable_base_evolves_under_gesture_and_returns_to_latest_base_smoothly():
    clock, controller = controller_at(0.0)
    assert controller.trigger_interaction()
    controller.set_runoff_activity(1.0)
    clock.advance(3.5)
    gesture_state = controller._state_at(clock.now())
    evolving_base = controller.base.brightness_percent
    assert evolving_base > 50
    assert gesture_state.cct_kelvin > 2700
    clock.advance(3.49)
    just_before = controller._state_at(clock.now())
    clock.advance(0.01)
    ended = controller._state_at(clock.now())
    assert ended.brightness_percent == pytest.approx(controller.base.brightness_percent)
    assert ended.cct_kelvin == 2700
    assert abs(ended.brightness_percent - just_before.brightness_percent) < 0.2


def test_activation_targets_current_runoff_and_deactivation_fades_to_blackout():
    clock = SimulatedClock()
    config = lighting_config()
    config["activation_fade_seconds"] = 4
    controller = HaloLightingController(config, clock=clock.now, ola_client=Ola())
    controller.set_runoff_activity(1.0)
    controller.activate()
    assert controller._state_at(0).brightness_percent == 0
    clock.advance(4)
    assert controller._state_at(clock.now()).brightness_percent == pytest.approx(70)
    controller._current = controller._state_at(clock.now())
    controller.deactivate()
    clock.advance(2)
    assert controller._state_at(clock.now()).brightness_percent == pytest.approx(35)
    clock.advance(2)
    assert controller._state_at(clock.now()).brightness_percent == 0


def test_timeline_round_trip_and_session_rebase(tmp_path):
    timestamps = np.array(["2003-01-01", "2003-01-02", "2003-01-03"], dtype="datetime64[D]")
    channels = {
        f"solenoid_{index}": {
            "timestamps": timestamps,
            "playback_times": np.array([0.0, 1.0, 2.0]),
            "values": np.array([0.0, index / 10, 1.0]),
        }
        for index in range(1, 7)
    }
    timeline = RunoffActivityTimeline.from_channels(channels)
    path = tmp_path / "runoff.npz"
    timeline.save(path)
    loaded = RunoffActivityTimeline.load(path)
    session = SessionRunoffActivity(loaded, 1.0)
    assert loaded.channel_names == tuple(channels)
    assert session.activity_at(0) == pytest.approx(0.35)
    assert session.activity_at(1) == 1.0


def test_tracked_production_timeline_contains_all_six_canonical_channels():
    timeline = RunoffActivityTimeline.load(ROOT / "runoff_state.npz")
    assert timeline.channel_names == tuple(f"solenoid_{index}" for index in range(1, 7))
    assert len(timeline.activity) == 6575
    assert np.all((timeline.activity >= 0) & (timeline.activity <= 1))


def test_session_updates_runoff_lighting_even_when_solenoid_actuation_is_suppressed():
    class Lighting:
        activation_delay_seconds = 0

        def __init__(self):
            self.activities = []

        def set_runoff_activity(self, value):
            self.activities.append(value)

        def activate(self):
            pass

        def step(self):
            pass

        def deactivate_async(self):
            pass

    class Activity:
        def activity_at(self, playback_time):
            return min(1.0, playback_time / 2)

    event = {"type": "solenoid", "target": "solenoid_1", "duration": 0.15, "playback_time": 10}
    clock, lighting = SimulatedClock(), Lighting()
    backend = NoActuationBackend()
    runtime = PlaybackSessionRuntime(
        lambda: PreparedSessionData([event], Activity()), clock,
        EventRouter({"solenoid": backend}), 30, initially_active=True,
        lighting_controller=lighting,
    )
    clock.advance(1)
    runtime.step()
    assert lighting.activities == pytest.approx([0.0, 0.5])


def test_play_events_no_actuation_flag_is_explicit():
    assert parse_args([]).no_actuation is False
    assert parse_args(["--no-actuation"]).no_actuation is True


def test_prepared_event_origin_does_not_change_event_timing_or_schema():
    def event(at):
        return {
            "playback_time": at, "timestamp": np.datetime64("2003-01-01"),
            "type": "solenoid", "target": "solenoid_1", "action": "pulse",
            "duration": 0.15, "metadata": {"frequency": 1.0, "source_value": 0.5},
        }

    events, origin = prepare_events_with_origin(
        [event(8), event(10), event(15)],
        {"start_date": "2003-01-01", "end_date": "2003-01-01", "random_segment": False},
    )
    assert origin == 8
    assert [item["playback_time"] for item in events] == [0, 2, 7]
    assert all(set(item) == {"playback_time", "timestamp", "type", "target", "action", "duration", "metadata"} for item in events)
