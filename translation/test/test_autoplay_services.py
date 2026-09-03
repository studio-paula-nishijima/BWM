import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VOICE_UNIT = REPOSITORY_ROOT / "services" / "voice_rack_services" / "whisper-runtime.service"
PLAYBACK_UNIT = REPOSITORY_ROOT / "services" / "translation services" / "play-events.service"
INSTALL_SCRIPT = REPOSITORY_ROOT / "translation" / "scripts" / "install-autoplay-services.sh"


class AutoplayServiceTests(unittest.TestCase):
    def assert_common_unit_contract(self, unit_path, interpreter, runner):
        text = unit_path.read_text(encoding="utf-8")
        self.assertIn("Type=simple", text)
        self.assertIn("After=local-fs.target", text)
        self.assertNotIn("network-online.target", text)
        self.assertNotIn("Wants=network", text)
        self.assertIn("WorkingDirectory=/home/raspi/BWM/translation", text)
        self.assertIn("Environment=PYTHONUNBUFFERED=1", text)
        self.assertIn(f"ExecStart={interpreter} -u {runner}", text)
        self.assertIn("TimeoutStopSec=10", text)
        self.assertIn("Restart=on-failure", text)
        self.assertIn("RestartSec=5", text)
        self.assertIn("WantedBy=multi-user.target", text)

    def test_whisper_runtime_unit_starts_the_voice_runner(self):
        self.assert_common_unit_contract(
            VOICE_UNIT,
            "/home/raspi/BWM/translation/whisper_venv/bin/python",
            "/home/raspi/BWM/translation/whisper_runtime.py",
        )

    def test_play_events_unit_starts_the_translation_runner(self):
        self.assert_common_unit_contract(
            PLAYBACK_UNIT,
            "/home/raspi/BWM/translation/translation_venv/bin/python",
            "/home/raspi/BWM/translation/play_events.py",
        )

    def test_install_script_installs_and_enables_only_the_new_units(self):
        text = INSTALL_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("services/voice_rack_services/whisper-runtime.service", text)
        self.assertIn("/etc/systemd/system/whisper-runtime.service", text)
        self.assertIn("/etc/systemd/system/play-events.service", text)
        self.assertIn("sudo systemctl daemon-reload", text)
        self.assertIn("sudo systemctl enable whisper-runtime.service play-events.service", text)
        self.assertIn("sudo systemctl restart whisper-runtime.service play-events.service", text)
        self.assertNotIn("disable ", text)
        self.assertNotIn("mask ", text)


if __name__ == "__main__":
    unittest.main()
