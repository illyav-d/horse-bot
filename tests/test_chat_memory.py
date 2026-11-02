import json
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path

from horsie.chat_memory import load_memory, memory_snapshot
from horsie.data_storage import write_json


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "memory.json"

    def load(self, now=10, wall_now=1010):
        return load_memory(self.path, now, wall_now, 1800, 128, 40, 24000)

    def test_restart_uses_wall_time_even_with_new_monotonic_clock(self):
        sessions = OrderedDict({(1, 2): {"messages": [
            {"at": 500, "payload": {"role": "user", "content": "hello"}}],
            "replies": [(505, 123)]}})
        write_json(self.path, memory_snapshot(sessions, 510, 1000))
        restored = self.load(now=10, wall_now=1010)
        self.assertEqual(restored[(1, 2)]["messages"][0]["at"], -10)
        self.assertEqual(restored[(1, 2)]["replies"], [(-5, 123)])
        self.assertFalse(self.load(wall_now=3000))

    def test_invalid_file_and_invalid_entries_do_not_crash(self):
        for value in ["broken JSON", "[]", '{"version": 2}', '{"version": 1, "channels": null}']:
            self.path.write_text(value, encoding="utf-8")
            self.assertFalse(self.load())
        payload = {"version": 1, "channels": [{"guild_id": 1, "channel_id": 2,
            "messages": [None, {"at": 1000, "payload": {"role": "system", "content": "bad"}},
                         {"at": 9000, "payload": {"role": "user", "content": "future"}},
                         {"at": 1000, "payload": {"role": "user", "content": "valid"}}],
            "replies": [[1000, 123], [9000, 999], [1000, "invalid"]]}]}
        write_json(self.path, payload)
        restored = self.load()[(1, 2)]
        self.assertEqual(len(restored["messages"]), 1)
        self.assertEqual(restored["messages"][0]["payload"]["content"], "valid")
        self.assertEqual(restored["replies"], [(0, 123)])

    def test_restore_enforces_channel_message_and_character_limits(self):
        channels = [{"guild_id": 1, "channel_id": cid,
            "messages": [{"at": 1000, "payload": {"role": "user", "content": "x" * 1000}} for _ in range(60)],
            "replies": []} for cid in range(1, 141)]
        write_json(self.path, {"version": 1, "channels": channels})
        restored = self.load()
        self.assertEqual(len(restored), 128)
        self.assertNotIn((1, 1), restored)
        for state in restored.values():
            self.assertEqual(len(state["messages"]), 24)

    def test_snapshot_does_not_change_when_live_messages_change(self):
        state = {"messages": [{"at": 500, "payload": {"role": "user", "content": "hello"}}], "replies": [(500, 123)]}
        snapshot = memory_snapshot({(1, 2): state}, 500, 1000)
        state["messages"][0]["payload"]["content"] = "changed"
        state["replies"].append((501, 124))
        self.assertEqual(snapshot["channels"][0]["messages"][0]["payload"]["content"], "hello")
        self.assertEqual(len(snapshot["channels"][0]["replies"]), 1)
