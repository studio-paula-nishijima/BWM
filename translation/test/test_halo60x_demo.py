import sys
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lighting.halo60x_demo import BLACKOUT, Halo60xState, build_halo60x_demo, state_to_dmx_channels


TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "halo60x_demo.py"
tool_spec = importlib.util.spec_from_file_location("halo60x_demo_tool", TOOL_PATH)
halo_tool = importlib.util.module_from_spec(tool_spec)
tool_spec.loader.exec_module(halo_tool)


class Halo60xDemoTests(unittest.TestCase):
    def test_matrix_is_row_major_and_held(self):
        cues = build_halo60x_demo()
        matrix = cues[1:10]
        self.assertEqual([(cue.end.brightness_percent, cue.end.cct_kelvin) for cue in matrix], [
            (100, 2700), (100, 4200), (100, 6500),
            (70, 2700), (70, 4200), (70, 6500),
            (45, 2700), (45, 4200), (45, 6500),
        ])
        self.assertTrue(all(cue.hold_seconds > 0 for cue in matrix))

    def test_transition_checks_change_one_control_at_a_time(self):
        cues = build_halo60x_demo()
        cct_up, cct_down = cues[11:13]
        brightness_up, brightness_down = cues[14:16]
        self.assertEqual((cct_up.start.brightness_percent, cct_up.end.brightness_percent), (70, 70))
        self.assertEqual((cct_down.start.brightness_percent, cct_down.end.brightness_percent), (70, 70))
        self.assertEqual((brightness_up.start.cct_kelvin, brightness_up.end.cct_kelvin), (4200, 4200))
        self.assertEqual((brightness_down.start.cct_kelvin, brightness_down.end.cct_kelvin), (4200, 4200))

    def test_blackout_bookends_and_strobe_is_always_off(self):
        cues = build_halo60x_demo()
        self.assertEqual(cues[0].start, BLACKOUT)
        self.assertEqual(cues[-1].end, BLACKOUT)
        self.assertTrue(all(state.strobe == 0 for cue in cues for state in (cue.start, cue.end)))

    def test_interpolation_is_smooth_and_independent(self):
        cues = build_halo60x_demo()
        cct_up = cues[11]
        middle = cct_up.state_at(cct_up.fade_seconds / 2)
        self.assertEqual(middle.brightness_percent, 70)
        self.assertEqual(middle.cct_kelvin, 4600)
        brightness_up = cues[14]
        middle = brightness_up.state_at(brightness_up.fade_seconds / 2)
        self.assertEqual(middle.cct_kelvin, 4200)
        self.assertEqual(middle.brightness_percent, 72.5)

    def test_invalid_strobe_cannot_enter_plan(self):
        with self.assertRaises(ValueError):
            Halo60xState(15, 2700, strobe=1)

    def test_demo_timings_are_configurable(self):
        cues = build_halo60x_demo(fade_seconds=1, hold_seconds=2,
                                  check_fade_seconds=3, blackout_hold_seconds=4)
        self.assertEqual((cues[0].hold_seconds, cues[1].fade_seconds, cues[1].hold_seconds), (4, 1, 2))
        self.assertEqual(cues[11].fade_seconds, 3)

    def test_dmx_profile_one_maps_intensity_cct_and_strobe(self):
        self.assertEqual(state_to_dmx_channels(Halo60xState(45, 2700)), (115, 0, 0))
        self.assertEqual(state_to_dmx_channels(Halo60xState(70, 4600)), (178, 128, 0))
        self.assertEqual(state_to_dmx_channels(Halo60xState(100, 6500)), (255, 255, 0))

    def test_slow_ola_submission_does_not_extend_cue_duration(self):
        class Clock:
            now = 0.0
            def __call__(self): return self.now
            def sleep(self, seconds): self.now += seconds
        clock, sent = Clock(), []
        class SlowOla:
            def send(self, frame): sent.append(frame); clock.now += 0.25
        cue = build_halo60x_demo(fade_seconds=1, hold_seconds=2)[1]
        halo_tool.play_cue(SlowOla(), cue, 1, 0.033, clock=clock, sleep=clock.sleep)
        self.assertLessEqual(clock.now, 3.3)
        self.assertLess(len(sent), 20)
        self.assertEqual(sent[-1][:3], bytes(state_to_dmx_channels(cue.end)))

    def test_static_cue_uses_ola_and_blackouts_on_exit(self):
        client = mock.MagicMock()
        with mock.patch.object(halo_tool, "OLAUniverseClient", return_value=client), \
                mock.patch.object(halo_tool, "play_cue") as play_cue:
            halo_tool.run_static(1, 1, .1, brightness=100, cct=6500, duration=10)
        self.assertEqual(play_cue.call_args.args[1].end, Halo60xState(100, 6500))
        self.assertTrue(client.send.called)
        client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
