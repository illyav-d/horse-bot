import tempfile
import unittest
from pathlib import Path

from horsie.data_storage import write_json
from horsie.long_term_memory import LongTermMemory


class LongTermTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "memory.json"
        self.memory = LongTermMemory(self.path)

    def test_personal_notes_follow_owner_only_within_same_server(self):
        self.memory.add(1, 20, 7, "personal", "I like racing")
        self.assertIn("I like racing", str(self.memory.context(1, 21, 7)))
        self.assertIsNone(self.memory.context(1, 20, 8))
        self.assertIsNone(self.memory.context(2, 20, 7))

    def test_channel_notes_and_summaries_stay_in_their_channel(self):
        self.memory.add(1, 20, 7, "channel", "Friday is race night")
        self.memory.update_summary((1, 20), "The group jokes about carrot taxes.", 123)
        self.assertIn("carrot taxes", str(self.memory.context(1, 20, 8)))
        self.assertIsNone(self.memory.context(1, 21, 8))
        self.assertIsNone(self.memory.context(2, 20, 8))

    def test_persistence_without_short_term_expiry_and_no_system_role(self):
        self.memory.add(1, 20, 7, "personal", "I like racing")
        self.memory.update_summary((1, 20), "Group racing plans", 1)
        write_json(self.path, {"version": 1, "channels": [], "long_term": self.memory.snapshot()})
        restored = LongTermMemory(self.path)
        self.assertEqual(restored.context(1, 20, 7)["role"], "user")
        self.assertIn("I like racing", restored.context(1, 20, 7)["content"])
        self.assertIn("Group racing plans", restored.context(1, 20, 7)["content"])

    def test_limits_duplicates_and_corrupt_file(self):
        first, _ = self.memory.add(1, 20, 7, "personal", "racing")
        again, _ = self.memory.add(1, 20, 7, "personal", "racing")
        self.assertEqual(first["id"], again["id"])
        self.assertIsNotNone(self.memory.add(1, 20, 7, "personal", "x" * 501)[1])
        for number in range(49):
            self.memory.add(1, 20, 7, "personal", str(number))
        self.assertIsNotNone(self.memory.add(1, 20, 7, "personal", "overflow")[1])
        self.path.write_text("not JSON")
        self.assertIsNone(LongTermMemory(self.path).context(1, 20, 7))

    def test_recall_finds_relevant_older_notes(self):
        self.memory.add(1, 20, 7, "personal", "My favourite game is Horsejack")
        for number in range(30):
            self.memory.add(1, 20, 7, "personal", "Unrelated note " + str(number))
        recalled = self.memory.context(1, 20, 7, "Which game is my favourite?")
        self.assertIn("Horsejack", recalled["content"])
