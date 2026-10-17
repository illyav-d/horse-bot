import os
import runpy
import tempfile
import unittest
from unittest.mock import patch

from horsie import horse_bot
from horsie.data_storage import DATA_DIR, PROJECT_ROOT, data_path
from horsie.horse_reactions import MACARONI_IMAGE, RAT_IMAGE, RAT_VIDEO


class LayoutTests(unittest.TestCase):
    def test_saves_and_assets_do_not_depend_on_working_directory(self):
        original = os.getcwd()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            try:
                os.chdir(directory)
                self.assertEqual(data_path("CARROT_FILE", "layout-test.json"), DATA_DIR / "layout-test.json")
                for asset in [MACARONI_IMAGE, RAT_IMAGE, RAT_VIDEO]:
                    self.assertTrue(asset.is_file(), asset)
            finally:
                os.chdir(original)

    def test_existing_local_saves_are_preserved_until_moved(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            legacy = root / "carrots.json"
            legacy.write_text('{}')
            with patch("horsie.data_storage.PROJECT_ROOT", root), patch("horsie.data_storage.DATA_DIR", root / "data"):
                self.assertEqual(data_path("CARROT_FILE", "carrots.json"), legacy)
                (root / "data").mkdir()
                legacy.rename(root / "data" / legacy.name)
                self.assertEqual(data_path("CARROT_FILE", "carrots.json"), root / "data" / legacy.name)

    def test_both_entrypoints_call_the_bot_main(self):
        with patch.object(horse_bot, "main") as start:
            runpy.run_path(str(PROJECT_ROOT / "main.py"), run_name="__main__")
            start.assert_called_once_with()
        with patch.object(horse_bot, "main") as start:
            runpy.run_module("horsie.__main__", run_name="__main__")
            start.assert_called_once_with()
