import random
import sys
import unittest
from copy import deepcopy
from pathlib import Path

import numpy as np
import yaml

TRANSLATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRANSLATION_ROOT))
sys.path.insert(0, str(TRANSLATION_ROOT / "src"))

from configs.runtime_config import RUNTIME_CONFIG, get_backup_button_pin, get_solenoid_pin_map
from events.playback_selection import select_random_segment
from play_events import prepare_events
from scheduling.safety import enforce_solenoid_safety
from scheduling.scheduler import generate_events


def event(playback_time, timestamp, target="solenoid_1"):
    return {
        "playback_time": playback_time,
        "timestamp": np.datetime64(timestamp),
        "type": "solenoid",
        "target": target,
        "action": "pulse",
        "duration": 0.15,
        "metadata": {"frequency": 1.0, "source_value": 0.5},
    }


class Stage1RegressionTests(unittest.TestCase):
    def test_production_runtime_remains_initially_active(self):
        self.assertIs(RUNTIME_CONFIG["playback"]["initially_active"], True)

    def test_scheduler_preserves_release_event_schema_and_order(self):
        events = generate_events(
            np.array(["2003-01-01", "2003-01-02"], dtype="datetime64[D]"),
            np.array([0.0, 1.0]), np.array([True, True]), 86400.0,
            {"freq_min": 1.0, "freq_max": 2.0, "t_on": 0.15,
             "scaling": "linear", "channel_name": "extra_channel", "time_scale": 86400.0},
        )
        self.assertEqual([round(item["playback_time"], 3) for item in events], [1.0, 1.5, 2.0])
        self.assertTrue(all(item["target"] == "extra_channel" for item in events))
        self.assertTrue(all(set(item) == {"playback_time", "timestamp", "type", "target", "action", "duration", "metadata"} for item in events))
        self.assertEqual([item["playback_time"] for item in events], sorted(item["playback_time"] for item in events))

    def test_scheduler_accumulates_constant_frequency_from_zero_phase(self):
        events = generate_events(
            np.array(["2003-01-01"] * 3, dtype="datetime64[D]"),
            np.zeros(3), np.ones(3, dtype=bool), 86400.0,
            {"freq_min": 1.0, "freq_max": 1.0, "t_on": 0.15,
             "scaling": "linear", "channel_name": "constant", "time_scale": 86400.0},
        )
        self.assertEqual([item["playback_time"] for item in events], [1.0, 2.0, 3.0])

    def test_scheduler_short_high_frequency_peak_is_not_held_by_old_pending_pulse(self):
        events = generate_events(
            np.array(["2003-01-01", "2003-01-02"], dtype="datetime64[D]"),
            np.array([0.0, 1.0]), np.ones(2, dtype=bool), 86400.0,
            {"freq_min": 0.1, "freq_max": 3.3, "t_on": 0.15,
             "scaling": "linear", "channel_name": "peak", "time_scale": 86400.0},
        )
        # The old scheduler set a 10 s horizon during the first interval and
        # missed this 1 s, 3.3 Hz peak completely.
        self.assertEqual([round(item["playback_time"], 3) for item in events], [1.273, 1.576, 1.879])
        self.assertTrue(all(item["metadata"]["frequency"] == 3.3 for item in events))

    def test_scheduler_resets_partial_phase_during_inactive_interval(self):
        events = generate_events(
            np.array(["2003-01-01"] * 4, dtype="datetime64[D]"),
            np.zeros(4), np.array([True, False, True, True]), 86400.0,
            {"freq_min": 0.6, "freq_max": 0.6, "t_on": 0.15,
             "scaling": "linear", "channel_name": "reset", "time_scale": 86400.0},
        )
        # The 0.6 phase from the first interval is discarded by inactivity;
        # reactivation takes a full fresh cycle.
        self.assertEqual([round(item["playback_time"], 3) for item in events], [3.667])

    def test_scheduler_emits_all_multiple_cycle_crossings(self):
        events = generate_events(
            np.array(["2003-01-01"], dtype="datetime64[D]"),
            np.zeros(1), np.ones(1, dtype=bool), 86400.0,
            {"freq_min": 3.5, "freq_max": 3.5, "t_on": 0.15,
             "scaling": "linear", "channel_name": "multiple", "time_scale": 86400.0},
        )
        self.assertEqual([round(item["playback_time"], 3) for item in events], [0.286, 0.571, 0.857])

    def test_current_canonical_channel_defaults_are_preserved(self):
        with (TRANSLATION_ROOT / "configs" / "channels.yaml").open(encoding="utf-8") as stream:
            channels = yaml.safe_load(stream)["channels"]
        self.assertEqual(list(channels), [f"solenoid_{number}" for number in range(1, 7)])
        self.assertTrue(all(channel["threshold"] == 0.0 for channel in channels.values()))
        self.assertTrue(all(channel["time_scale"] == 182800 for channel in channels.values()))
        self.assertEqual(channels["solenoid_4"]["csv_path"].rsplit("/", 1)[-1], "ID_174.csv")

    def test_playback_preparation_keeps_filter_rebase_and_seeded_segment_semantics(self):
        score = [event(8.0, "2002-12-31"), event(10.0, "2003-01-01"), event(15.0, "2003-01-02"), event(20.0, "2003-01-03")]
        config = {"start_date": "2003-01-01", "end_date": "2003-01-03", "random_segment": False}
        prepared = prepare_events(deepcopy(score), config)
        self.assertEqual([item["playback_time"] for item in prepared], [0.0, 5.0, 10.0])
        random.seed(7)
        selected = select_random_segment(deepcopy(prepared), 4.0)
        self.assertEqual([item["playback_time"] for item in selected], [5.0])

    def test_hardware_topology_is_dynamic_and_reserves_non_outputs(self):
        pin_map = get_solenoid_pin_map()
        self.assertEqual(pin_map, {"solenoid_1": 18, "solenoid_2": 23, "solenoid_3": 24, "solenoid_4": 22, "solenoid_5": 25, "solenoid_6": 27})
        self.assertEqual(get_backup_button_pin(), 17)
        self.assertNotIn(14, pin_map.values())
        self.assertNotIn(15, pin_map.values())
        synthetic = {"solenoids": {"a": 4, "b": 5, "c": 6, "d": 12}, "reserved_pins": {"uart_tx": 14}}
        self.assertEqual(get_solenoid_pin_map(synthetic), synthetic["solenoids"])

    def test_stage1_safety_config_is_connected_but_disabled(self):
        events = [event(0.0, "2003-01-01"), event(0.01, "2003-01-01")]
        self.assertIs(enforce_solenoid_safety(events, RUNTIME_CONFIG["safety"]), events)


if __name__ == "__main__":
    unittest.main()
