from pathlib import Path
import importlib.util
import sys

import numpy as np
import pytest

MODULE_PATH = Path(__file__).parents[1] / "tools" / "export_score.py"
SPEC = importlib.util.spec_from_file_location("esp_export_score", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def record(playback, timestamp, target="solenoid_1", duration=.15):
    return {"playback_time": playback, "timestamp": np.datetime64(timestamp), "type": "solenoid",
            "target": target, "action": "pulse", "duration": duration, "metadata": {}}


def convert(items, start="2003-01-01", end="2017-12-31"):
    return module.convert(np.array(items, dtype=object), source_sha256="a" * 64,
                          config_sha256="b" * 64, start_date=start, end_date=end,
                          channel_names=[f"solenoid_{i}" for i in range(1, 7)])


def test_date_filter_mapping_rebase_and_half_up_quantization():
    result = convert([
        record(1.0, "2002-12-31"),
        record(4.0004, "2003-01-01", "solenoid_2"),
        record(4.0015, "2017-12-31", "solenoid_6"),
        record(9.0, "2018-01-01"),
    ])
    assert result.source_count == 4
    assert [(e.time_ms, e.channel, e.duration_ms) for e in result.events] == [(0, 1, 150), (1, 5, 150)]


@pytest.mark.parametrize("change", [
    {"type": "motor"}, {"action": "on"}, {"target": "solenoid_7"},
    {"duration": .501}, {"playback_time": -1},
])
def test_rejects_unsupported_records(change):
    item = record(1, "2003-01-01")
    item.update(change)
    with pytest.raises(module.ExportError):
        convert([item])


def test_current_score_and_generated_provenance(tmp_path):
    translation = Path(__file__).parents[2]
    result, runtime, reactions = module.load_and_convert(translation)
    assert result.source_count == 6253
    assert result.filtered_count > 0
    assert set(result.per_target) == {f"solenoid_{i}" for i in range(1, 7)}
    module.write_header(result, tmp_path / "score.h")
    module.write_artistic_config(runtime, reactions, tmp_path / "config.h")
    assert result.source_sha256 in (tmp_path / "score.h").read_text()
    assert "kSolenoidAdmissionDelayMs = 4000u" in (tmp_path / "config.h").read_text()
