import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from horsie.changelog_history import ChangelogHistory
from horsie import horse_bot as h


class ChangelogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "changelog.json"
        self.channel = NS()
        self.now = 1_800_000_000

    async def test_recent_post_only_sends_additions_across_restarts(self):
        history = ChangelogHistory(self.path)
        history.record(1, ["old"], self.now)
        restarted = ChangelogHistory(self.path)
        entries, known = await restarted.select(1, self.channel, None, ["new", "old"], self.now + 60)
        self.assertEqual(entries, ["new"])
        restarted.record(1, known + entries, self.now + 60)
        again = ChangelogHistory(self.path)
        self.assertEqual((await again.select(1, self.channel, None, ["newer", "new", "old"], self.now + 120))[0], ["newer"])
        self.assertEqual((await again.select(1, self.channel, None, ["new", "old"], self.now + 180))[0], [])

    async def test_full_changelog_after_an_hour_and_in_other_servers(self):
        history = ChangelogHistory(self.path)
        history.record(1, ["old"], self.now)
        for guild_id, now in [(1, self.now + 3600), (2, self.now + 60)]:
            with self.subTest(guild_id=guild_id):
                self.assertEqual(await history.select(guild_id, self.channel, None, ["new", "old"], now), (["new", "old"], []))

    async def test_bootstrap_reads_only_own_changelog_embeds(self):
        def message(author, title, description):
            return NS(author=NS(id=author), webhook_id=None,
                      embeds=[discord.Embed(title=title, description=description)])
        messages = [
            message(42, "Horsie Bot v1.8.6 is online", "**Changelog additions:**\n- recent"),
            message(42, "Horsie Bot v1.8.5 is online", "**Changelog:**\n- old"),
            message(99, "Horsie Bot v1.8.6 is online", "**Changelog:**\n- new"),
            message(42, "Horse story", "**Changelog:**\n- new"),
        ]
        async def iterate(**kwargs):
            for item in messages:
                yield item
        self.channel.history = MagicMock(side_effect=iterate)
        history = ChangelogHistory(self.path)
        entries, known = await history.select(1, self.channel, 42, ["new", "recent", "old"], self.now)
        self.assertEqual(entries, ["new"])
        self.assertEqual(known, ["recent", "old"])
        self.assertEqual(self.channel.history.call_args.kwargs["after"].timestamp(), self.now - 3600)

    async def test_successful_send_is_saved_but_failed_send_is_not(self):
        channel = NS(send=AsyncMock(), permissions_for=lambda _: NS(attach_files=False), guild=NS(me=object()))
        guild = NS(id=1)
        async def post(_, sender):
            await sender(channel)
        with patch.object(h, "CHANGELOG_HISTORY_FILE", self.path), patch.object(h, "CHANGELOG", ["old"]), \
                patch.object(h.bot, "_connection") as connection, patch.object(h, "post_to_guild", side_effect=post):
            connection.guilds = [guild]
            connection.user = None
            await h.post_changelog_to_discord()
            self.assertEqual(json.loads(self.path.read_text())["1"]["entries"], ["old"])
            await h.post_changelog_to_discord()
            channel.send.assert_awaited_once()
            with patch.object(h, "CHANGELOG", ["new", "old"]):
                channel.send.side_effect = discord.HTTPException(NS(status=500, reason="failed"), "failed")
                with self.assertRaises(discord.HTTPException):
                    await h.post_changelog_to_discord()
                self.assertEqual(json.loads(self.path.read_text())["1"]["entries"], ["old"])
                channel.send.side_effect = None
                await h.post_changelog_to_discord()
                self.assertEqual(channel.send.await_args.kwargs["embed"].description, "**Changelog additions:**\n- new")
                self.assertEqual(json.loads(self.path.read_text())["1"]["entries"], ["old", "new"])
