import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.ext import commands

from horsie import horse_bot
from horsie.race_betting import RaceBets, collect_race_bets, winner_pages


HORSES = ["Horse A", "Horse B", "Horse C", "Horse D"]


def message(user, choice, channel=1, bot=False):
    return SimpleNamespace(
        channel=SimpleNamespace(id=channel), content=str(choice),
        author=SimpleNamespace(id=user, display_name=f"Player {user}", bot=bot),
    )


class FakeBot:
    def __init__(self):
        self.listeners = []

    def add_listener(self, listener, event):
        self.listeners.append(listener)

    def remove_listener(self, listener, event):
        self.listeners.remove(listener)

    async def pick(self, user, choice):
        for listener in list(self.listeners):
            await listener(message(user, choice))


class RaceTests(unittest.IsolatedAsyncioTestCase):
    def test_large_winner_list_is_split_without_losing_players(self):
        winners = [f"Player {i} (+1 carrot, now 42)" for i in range(1000)]
        pages = list(winner_pages(winners))
        self.assertTrue(all(len(page) <= 1800 for page in pages))
        self.assertEqual("\n".join(pages).splitlines(), winners)

    async def test_simultaneous_picks_and_replacements(self):
        collector = RaceBets(1, HORSES, lambda: 0)
        await asyncio.gather(*(collector.on_message(message(i, i % 4 + 1)) for i in range(1000)))
        self.assertEqual(len(collector.bets), 1000)
        await collector.on_message(message(1, 4))
        self.assertEqual(len(collector.bets), 1000)
        self.assertEqual(collector.bets[1]["choice"], 4)
        self.assertLess(len(collector.render()), 2000)

    async def test_large_race_rewards_every_winner_once_and_splits_results(self):
        bets = {i: {"user_id": i, "name": f"Player {i}", "choice": 1} for i in range(1000)}
        ctx = SimpleNamespace(send=AsyncMock())
        with patch.object(horse_bot, "collect_race_bets", AsyncMock(return_value=bets)), \
                patch.object(horse_bot.asyncio, "sleep", AsyncMock()), \
                patch.object(horse_bot.random, "sample", return_value=HORSES), \
                patch.object(horse_bot.random, "random", return_value=1), \
                patch.object(horse_bot.random, "randint", return_value=3), \
                patch.object(horse_bot.random, "choice", side_effect=lambda values: values[0]), \
                patch.object(horse_bot, "add_carrot", return_value=1) as reward:
            await horse_bot.horserace.callback(ctx)
        self.assertEqual(reward.call_count, 1000)
        self.assertEqual({call.args[0] for call in reward.call_args_list}, set(bets))
        self.assertTrue(all(len(call.args[0]) <= 2000 for call in ctx.send.await_args_list))

    async def test_ignores_other_channels_bots_and_invalid_choices(self):
        collector = RaceBets(1, HORSES, lambda: 0)
        for msg in [message(1, 1, channel=2), message(2, 2, bot=True), message(3, 0), message(4, 5), message(5, "!horse")]:
            await collector.on_message(msg)
        self.assertFalse(collector.bets)

    async def test_deadline_and_closed_state(self):
        now = [0]
        collector = RaceBets(1, HORSES, lambda: now[0])
        collector.deadline = 20
        await collector.on_message(message(1, 1))
        now[0] = 20
        await collector.on_message(message(2, 2))
        await collector.on_message(message(1, 4))
        self.assertEqual(list(collector.bets), [1])
        self.assertEqual(collector.bets[1]["choice"], 1)
        collector.closed = True
        now[0] = 0
        await collector.on_message(message(3, 3))
        self.assertEqual(len(collector.bets), 1)

    async def test_channels_collect_independently(self):
        one = RaceBets(1, HORSES, lambda: 0)
        two = RaceBets(2, HORSES, lambda: 0)
        for msg in [message(1, 1), message(1, 4, channel=2)]:
            await asyncio.gather(one.on_message(msg), two.on_message(msg))
        self.assertEqual(one.bets[1]["choice"], 1)
        self.assertEqual(two.bets[1]["choice"], 4)

    async def test_picks_continue_while_discord_edit_is_blocked(self):
        bot = FakeBot()
        edit_started, release_edit = asyncio.Event(), asyncio.Event()
        board = Mock()

        async def edit(**kwargs):
            edit_started.set()
            await release_edit.wait()

        board.edit = AsyncMock(side_effect=edit)
        ctx = SimpleNamespace(channel=SimpleNamespace(id=1), send=AsyncMock(return_value=board))
        task = asyncio.create_task(collect_race_bets(bot, ctx, HORSES, duration=0.1, refresh_interval=0.001))
        try:
            while not bot.listeners:
                await asyncio.sleep(0)
            await bot.pick(1, 1)
            await asyncio.wait_for(edit_started.wait(), timeout=1)
            await asyncio.gather(*(bot.pick(i, 2) for i in range(2, 102)))
            await bot.pick(1, 4)
            release_edit.set()
            bets = await asyncio.wait_for(task, timeout=2)
            self.assertEqual(len(bets), 101)
            self.assertEqual(bets[1]["choice"], 4)
            self.assertEqual(ctx.send.await_count, 1)
            self.assertFalse(bot.listeners)
            self.assertIn("locked", board.edit.call_args.kwargs["content"])
        finally:
            release_edit.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_listener_cleanup_on_send_failure(self):
        bot = FakeBot()
        ctx = SimpleNamespace(channel=SimpleNamespace(id=1), send=AsyncMock(side_effect=RuntimeError("send failed")))
        with self.assertRaises(RuntimeError):
            await collect_race_bets(bot, ctx, HORSES)
        self.assertFalse(bot.listeners)

    async def test_failed_board_edits_do_not_lose_picks(self):
        bot = FakeBot()
        board = Mock()
        board.edit = AsyncMock(side_effect=discord.HTTPException(SimpleNamespace(status=500, reason="Error"), "edit failed"))
        ctx = SimpleNamespace(channel=SimpleNamespace(id=1), send=AsyncMock(return_value=board))
        task = asyncio.create_task(collect_race_bets(bot, ctx, HORSES, duration=0.02, refresh_interval=0.001))
        while not bot.listeners:
            await asyncio.sleep(0)
        await bot.pick(1, 3)
        self.assertEqual((await task)[1]["choice"], 3)
        self.assertFalse(bot.listeners)

    async def test_listener_cleanup_on_cancellation(self):
        bot = FakeBot()
        ctx = SimpleNamespace(channel=SimpleNamespace(id=1), send=AsyncMock())
        task = asyncio.create_task(collect_race_bets(bot, ctx, HORSES))
        while not bot.listeners:
            await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(bot.listeners)

    async def test_concurrency_rejects_same_channel_allows_others_and_releases(self):
        guard = horse_bot.horserace._max_concurrency
        one = SimpleNamespace(channel=SimpleNamespace(id=9001))
        two = SimpleNamespace(channel=SimpleNamespace(id=9002))
        await guard.acquire(one)
        try:
            with self.assertRaises(commands.MaxConcurrencyReached):
                await guard.acquire(one)
            await guard.acquire(two)
            await guard.release(two)
        finally:
            await guard.release(one)
        await guard.acquire(one)
        await guard.release(one)

    async def test_removed_commands_not_registered(self):
        from horsie.game_commands import GameCommands
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        async with bot:
            await bot.add_cog(GameCommands(bot, AsyncMock()))
            self.assertIsNotNone(bot.get_command("wow"))
            self.assertIsNotNone(bot.get_command("xivtrend"))
            self.assertIsNone(bot.get_command("xivlogs"))
            self.assertIsNone(bot.get_command("xivrecap"))
            self.assertEqual(set(bot.get_command("wow").params), {"region", "realm", "character"})
            self.assertFalse(bot.get_command("wow").ignore_extra)


if __name__ == "__main__":
    unittest.main()
