import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import horse_bot as bot
from data_storage import data_path


class CarrotStorageTests(unittest.TestCase):
    def test_volume_default_and_explicit_override(self):
        with patch.dict(os.environ, {"RAILWAY_VOLUME_MOUNT_PATH": "/data"}, clear=True):
            self.assertEqual(data_path("CARROT_FILE", "carrots.json"), Path("/data/carrots.json"))
            with patch.dict(os.environ, {"CARROT_FILE": "custom.json"}):
                self.assertEqual(data_path("CARROT_FILE", "carrots.json"), Path("custom.json"))

    def test_existing_volume_scores_and_awards_survive_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            live = root / "volume" / "carrots.json"
            with patch.object(bot, "CARROT_FILE", live):
                self.assertEqual(bot.load_carrots(), {})
                bot.save_carrots({"123": {"name": "Kate", "carrots": 8}})
                self.assertEqual(bot.get_carrot_count(123), 8)
                self.assertEqual(bot.add_carrot(123, "Kate"), 9)
                self.assertEqual(bot.add_carrot(123, "Kate"), 10)
                self.assertEqual(bot.get_carrot_count(123), 10)
                self.assertEqual(json.loads(live.read_text())["123"]["carrots"], 10)

    def test_corrupt_save_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            live = Path(folder) / "carrots.json"
            live.write_text("broken JSON")
            with patch.object(bot, "CARROT_FILE", live):
                with self.assertRaises(RuntimeError):
                    bot.add_carrot(123, "Kate")
            self.assertEqual(live.read_text(), "broken JSON")

    def test_failed_atomic_replace_keeps_previous_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            live = Path(folder) / "carrots.json"
            original = json.dumps({"123": {"name": "Kate", "carrots": 9}})
            live.write_text(original)
            with patch.object(bot, "CARROT_FILE", live), patch.object(Path, "replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    bot.add_carrot(123, "Kate")
            self.assertEqual(live.read_text(), original)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
