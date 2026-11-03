import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from horsie.chatgpt_controls import ChatGPTControls, ControlError


class ControlTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "controls.json"

    def test_switch_survives_restarts_and_has_no_budget_or_audience_settings(self):
        controls = ChatGPTControls(self.path)
        self.assertEqual(controls.snapshot(), {"enabled": True})
        controls.update(enabled=False)
        restarted = ChatGPTControls(self.path)
        self.assertEqual(restarted.snapshot(), {"enabled": False})
        restarted.update(enabled=True)
        self.assertEqual(ChatGPTControls(self.path).snapshot(), {"enabled": True})

    def test_corruption_pauses_until_settings_can_be_saved(self):
        self.path.write_text("not JSON")
        controls = ChatGPTControls(self.path)
        self.assertFalse(controls.snapshot()["enabled"])
        self.assertFalse(controls.storage_ok)
        controls.update(enabled=True)
        self.assertTrue(ChatGPTControls(self.path).snapshot()["enabled"])

    def test_failed_off_write_still_blocks_this_process(self):
        controls = ChatGPTControls(self.path)
        with patch("horsie.chatgpt_controls.write_json", side_effect=OSError()):
            with self.assertRaises(ControlError):
                controls.update(enabled=False)
        self.assertFalse(controls.snapshot()["enabled"])
        self.assertFalse(controls.storage_ok)
