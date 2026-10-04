import sys
import inspect
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from configs.whisper import COOLDOWN_SECONDS, STARTUP_COOLDOWN_SECONDS
import whisper_runtime
from whisper_runtime import detector_trigger_admitted


def admitted(*, startup_now, wall_now, startup_deadline=30, last_emitted_at=0,
             startup_crossing=True, cooldown_seconds=60):
    return detector_trigger_admitted(
        crossing=startup_crossing,
        monotonic_now=startup_now,
        wall_now=wall_now,
        startup_deadline=startup_deadline,
        last_emitted_at=last_emitted_at,
        cooldown_seconds=cooldown_seconds,
    )


def test_configured_startup_cooldown_is_independent_of_inter_trigger_cooldown():
    assert STARTUP_COOLDOWN_SECONDS == 30
    assert COOLDOWN_SECONDS == 60


def test_detector_crossing_is_suppressed_during_startup_but_admitted_at_deadline():
    assert not admitted(startup_now=29.999, wall_now=100)
    assert admitted(startup_now=30, wall_now=100)


def test_existing_inter_trigger_cooldown_still_spaces_emitted_detector_triggers():
    assert not admitted(startup_now=90, wall_now=160, last_emitted_at=100)
    assert admitted(startup_now=90, wall_now=160.001, last_emitted_at=100)


def test_startup_and_inter_trigger_cooldowns_are_independent():
    assert not admitted(startup_now=29, wall_now=1000, last_emitted_at=0)
    assert not admitted(startup_now=31, wall_now=150, last_emitted_at=100)
    assert admitted(startup_now=31, wall_now=161, last_emitted_at=100)


def test_zero_startup_cooldown_preserves_immediate_detector_admission():
    assert admitted(startup_now=0, wall_now=100, startup_deadline=0)


def test_non_crossing_is_never_promoted_by_either_time_gate():
    assert not admitted(startup_now=1000, wall_now=1000, startup_crossing=False)


def test_detector_processing_logging_and_button_remain_outside_startup_gate():
    source = inspect.getsource(whisper_runtime.main)
    detector_processing = source.index("pipeline_result = detector.process")
    startup_gate = source.index("if detector_trigger_admitted")
    button_admission = source.index("button_presses.get_nowait")
    frame_logging = source.index("csv_logger.log")

    assert detector_processing < startup_gate < button_admission < frame_logging
    button_block = source[button_admission:source.index("except queue.Empty", button_admission)]
    assert "startup_trigger_deadline" not in button_block
