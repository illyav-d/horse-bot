import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from discord.ext import commands

from horsie import game_commands as g


class Context:
    def __init__(self):
        self.send = AsyncMock()

    def typing(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class SummaryTests(unittest.TestCase):
    def test_sales_window_boundaries_and_invalid_sales(self):
        now = 200000
        entries = [{"timestamp": now - age, "pricePerUnit": price, "quantity": 2}
                   for age, price in [(0, 100), (86400, 200), (86401, 300),
                                      (172800, 500), (172801, 999), (-1, 999), (5, 0)]]
        result = g.summarize_sales(entries, now)
        self.assertEqual(result["recent_median"], 150)
        self.assertEqual(result["previous_median"], 400)
        self.assertEqual(result["units"], 4)
        self.assertEqual(result["recent_count"], 2)

    def test_empty_sales(self):
        self.assertIsNone(g.summarize_sales([], 100)["recent_median"])

class CommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = g.GameCommands(Mock(), AsyncMock(return_value=(1, "Test item")))
        self.ctx = Context()

    async def test_retail_card(self):
        data = {"name": "Horse", "realm": "Silvermoon", "profile_url": "https://raider.io/characters/eu/silvermoon/Horse",
                "gear": {"item_level_equipped": 200}, "mythic_plus_scores_by_season": [{"scores": {"all": 1234}}],
                "raid_progression": {"raid": {"summary": "2/8 H"}}}
        with patch.object(g, "request_json", AsyncMock(return_value=data)) as request:
            await self.cog.wow.callback(self.cog, self.ctx, "EU", "silvermoon", "Horse")
        embed = self.ctx.send.call_args.kwargs["embed"]
        self.assertIn("Raider.IO", embed.footer.text)
        self.assertEqual(embed.fields[1].value, "1234")
        self.assertEqual(request.call_args.kwargs["params"]["region"], "eu")

    async def test_bad_wow_region(self):
        with self.assertRaises(g.GameAPIError):
            await self.cog.wow.callback(self.cog, self.ctx, "xx", "realm", "name")

    async def test_price_trends_filter_quality_and_calculate_change(self):
        now = 200000
        entries = [{"timestamp": now - age, "pricePerUnit": price, "quantity": 2, "hq": True}
                   for age, price in [(1, 100), (2, 100), (3, 100), (90000, 200), (90001, 200), (90002, 200)]]
        entries.append({"timestamp": now, "pricePerUnit": 10000, "quantity": 100, "hq": False})
        listings = {"listings": [{"pricePerUnit": 90, "worldName": "Omega", "hq": True}, {"pricePerUnit": 1, "hq": False}]}
        with patch.object(g, "request_json", AsyncMock(side_effect=[listings, {"entries": entries}])), patch.object(g.time, "time", return_value=now):
            await self.cog.xivtrend.callback(self.cog, self.ctx, "Light", item="Test item --hq")
        embed = self.ctx.send.call_args.kwargs["embed"]
        fields = {f.name: f.value for f in embed.fields}
        self.assertIn("90 gil", fields["Cheapest listed / item"])
        self.assertIn("-50.0%", fields["Median price change"])
        self.assertEqual(fields["Observed units sold (24h)"], "6")
        self.cog.find_item.assert_awaited_once_with("Test item")

    async def test_empty_market_and_no_item(self):
        with patch.object(g, "request_json", AsyncMock(side_effect=[{}, {}])):
            await self.cog.xivtrend.callback(self.cog, self.ctx, "Light", item="Test")
        embed = self.ctx.send.call_args.kwargs["embed"]
        self.assertIn("Too few", next(f.value for f in embed.fields if f.name == "Trend"))
        self.cog.find_item.return_value = None
        with self.assertRaises(g.GameAPIError):
            await self.cog.xivtrend.callback(self.cog, self.ctx, "Light", item="Unknown")

    async def test_http_errors_have_safe_messages(self):
        for status in [401, 403, 404, 429, 500]:
            response = AsyncMock()
            response.status = status
            request = Mock()
            request.__aenter__ = AsyncMock(return_value=response)
            request.__aexit__ = AsyncMock(return_value=False)
            session = Mock()
            session.request.return_value = request
            with self.assertRaises(g.GameAPIError):
                await g.request_json(session, "GET", "https://example.invalid")

    async def test_usage_and_timeout_messages(self):
        self.ctx.command = self.cog.wow
        await self.cog.cog_command_error(self.ctx, commands.MissingRequiredArgument(self.cog.wow.params["region"]))
        self.assertIn("Usage:", self.ctx.send.call_args.args[0])
        await self.cog.cog_command_error(self.ctx, commands.CommandInvokeError(asyncio.TimeoutError()))
        self.assertIn("try again", self.ctx.send.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
