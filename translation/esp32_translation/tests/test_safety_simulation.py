from pathlib import Path
import importlib.util
import sys

MODULE_PATH = Path(__file__).parents[1] / "tools" / "simulate_safety.py"
SPEC = importlib.util.spec_from_file_location("esp_safety_sim", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_complete_score_and_every_reaction_pass_emergency_guards():
    report = module.run(Path(__file__).parents[1])
    assert "Emergency guard rejections" in report
    assert report.count("| 0 |") == 6


def test_channel_serialization_preserves_triple_tap_spacing_floor():
    pulses = [module.Pulse(0, 150, 0), module.Pulse(200, 150, 0),
              module.Pulse(285, 150, 0), module.Pulse(400, 150, 0)]
    serialized = module.serialize_channels(pulses)
    assert [pulse.at for pulse in serialized] == [0, 200, 390, 580]
    assert module.emergency_rejections(serialized) == {}
