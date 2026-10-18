import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from horsie.reality_check import CAUTION, CheckError, RealityCheck, assess, image_urls


def message(content="", attachments=None, embeds=None, id=100):
    channel = NS(id=20, fetch_message=AsyncMock(), typing=MagicMock())
    channel.typing.return_value.__aenter__ = AsyncMock()
    channel.typing.return_value.__aexit__ = AsyncMock(return_value=False)
    return NS(content=content, attachments=attachments or [], embeds=embeds or [],
              id=id, jump_url=f"https://discord.com/channels/1/20/{id}", reference=None,
              author=NS(id=7, bot=False), webhook_id=None, guild=NS(id=1),
              channel=channel, reply=AsyncMock(), created_at=discord.utils.utcnow())


def photo(id=90):
    return message(attachments=[NS(content_type="image/png", size=500,
                                  url="https://cdn.discordapp.com/attachments/1/2/test.png")], id=id)


def history(channel, messages):
    async def iterate(**kwargs):
        for msg in messages:
            yield msg
    channel.history = MagicMock(side_effect=iterate)


class RealityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = RealityCheck(NS(user=NS(id=42)))
        self.env = patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_mention_variants_find_image_past_intervening_chat(self):
        for text in ["<@42> is this real?", "is it real <@!42>", "<@42> real or AI?",
                     "<@42> is that AI?", "<@42> if its real"]:
            with self.subTest(text=text):
                cog = RealityCheck(NS(user=NS(id=42)))
                request, image = message(text), photo()
                history(request.channel, [message("hello", id=99), image, photo(id=89)])
                with patch("horsie.reality_check.assess", AsyncMock(return_value="assessment")) as check:
                    await cog.on_message(request)
                self.assertEqual(check.await_args.args[1], [image.attachments[0].url])
                self.assertIn(image.jump_url, request.reply.await_args.args[0])
                self.assertFalse(request.reply.await_args.kwargs["allowed_mentions"].everyone)
                request.channel.history.assert_called_once_with(limit=50, before=request)

    async def test_ignores_unmentioned_other_bots_webhooks_dms_and_unrelated_mentions(self):
        cases = [message("is this real?"), message("<@99> is this real?"),
                 message("<@42> hello"), message("<@42> is this reality?")]
        for field, value in [("author", NS(id=7, bot=True)), ("webhook_id", 8), ("guild", None)]:
            msg = message("<@42> is this real?")
            setattr(msg, field, value)
            cases.append(msg)
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            for msg in cases:
                await self.cog.on_message(msg)
                msg.reply.assert_not_awaited()
            check.assert_not_awaited()

    async def test_reply_is_explicit_and_cannot_cross_channels(self):
        request = message("<@42> is this real?")
        request.reference = NS(channel_id=20, message_id=90)
        request.channel.fetch_message.return_value = photo()
        self.assertEqual((await self.cog.target(request)).id, 90)
        request.reference.channel_id = 999
        with self.assertRaises(CheckError):
            await self.cog.target(request)
        request.channel.fetch_message.assert_awaited_once()

    async def test_attached_request_image_takes_priority(self):
        request = photo()
        self.assertIs(await self.cog.target(request), request)

    async def test_missing_image_and_missing_key_never_call_api(self):
        request = message("<@42> is this real?")
        history(request.channel, [message("just text")])
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            await self.cog.on_message(request)
            self.assertIn("couldn't find", request.reply.await_args.args[0])
            self.assertFalse(self.cog.active_channels)
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                request.author.id = 8
                await self.cog.on_message(request)
            self.assertIn("OPENAI_API_KEY", request.reply.await_args.args[0])
            check.assert_not_awaited()

    async def test_cooldown_and_failure_release_busy_channel(self):
        request = message("<@42> is this real?")
        history(request.channel, [photo()])
        with patch("horsie.reality_check.assess", AsyncMock(side_effect=asyncio.TimeoutError)) as check:
            await self.cog.on_message(request)
            await self.cog.on_message(request)
            check.assert_awaited_once()
        self.assertFalse(self.cog.active_channels)
        self.assertIn("couldn't finish", request.reply.await_args.args[0])

    async def test_deleted_reply_does_not_fall_back(self):
        request = message("<@42> is this real?")
        request.reference = NS(channel_id=20, message_id=90)
        request.channel.fetch_message.side_effect = discord.NotFound(NS(status=404, reason="Gone"), "gone")
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            await self.cog.on_message(request)
            check.assert_not_awaited()
        self.assertFalse(self.cog.active_channels)

    async def test_busy_channel_does_not_start_another_request(self):
        request = message("<@42> is this real?")
        self.cog.active_channels.add(request.channel.id)
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            await self.cog.on_message(request)
            check.assert_not_awaited()
        self.assertIn("already checking", request.reply.await_args.args[0])
        self.assertIn(request.channel.id, self.cog.active_channels)

    def test_links_previews_and_unsupported_files(self):
        direct = message("https://example.com/image.jpg?x=1")
        self.assertEqual(image_urls(direct), [direct.content])
        embed = discord.Embed(type="rich").set_thumbnail(url="https://example.com/image.png")
        self.assertEqual(image_urls(message(embeds=[embed])), ["https://example.com/image.png"])
        self.assertEqual(image_urls(message("https://example.com/clip.gif")), [])
        self.assertEqual(image_urls(message(attachments=[NS(content_type="video/mp4")])), [])
        large = photo()
        large.attachments[0].size = 9 * 1024 * 1024
        with self.assertRaises(CheckError):
            image_urls(large)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def call_api(self, status=200, body=None):
        response = MagicMock(status=status)
        response.json = AsyncMock(return_value=body)
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch("horsie.reality_check.aiohttp.ClientSession", factory):
            answer = await assess("image", ["https://example.com/image.png"])
        return answer, session.post.call_args.kwargs["json"]

    async def test_request_and_visible_uncertainty(self):
        body = {"status": "completed", "output": [{"type": "message", "content": [{
            "type": "output_text", "text": '{"verdict":"Inconclusive","reasons":"No reliable clues."}',
        }]}]}
        answer, payload = await self.call_api(body=body)
        self.assertIn(CAUTION, answer)
        self.assertIn("Inconclusive", answer)
        self.assertFalse(payload["store"])
        self.assertEqual(payload["input"][0]["content"][1]["type"], "input_image")

    async def test_api_failures_and_bad_or_incomplete_responses(self):
        for status, body in [(429, {}), (401, {}), (500, {}), (200, {}),
                             (200, {"status": "incomplete"}),
                             (200, {"status": "completed", "output": []})]:
            with self.subTest(status=status, body=body), self.assertRaises(CheckError):
                await self.call_api(status, body)
