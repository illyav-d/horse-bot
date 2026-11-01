import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

from horsie.horse_chat import HorseChat, TTL, chat_completion
from horsie.message_routing import is_image_check
from horsie.reality_check import CheckError, QuotaError, RealityCheck
from tests.test_reality_check import message


class ChatTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = NS(user=NS(id=42))
        self.cog = HorseChat(self.bot)
        self.env = patch.dict(os.environ, {"GROQ_API_KEY": "test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def request(self, content="<@42> hello", id=100):
        msg = message(content, id=id)
        msg.reply.return_value = NS(id=id + 1000)
        return msg

    async def test_chat_and_image_routes_are_exclusive(self):
        for content, image_check in [
            ("<@42>", True), ("<@!42> is this real?", True),
            ("is it real <@42>", True), ("<@42> real or AI?", True),
            ("<@42> how are you?", False), ("<@!42> hello", False),
        ]:
            with self.subTest(content=content):
                self.assertEqual(is_image_check(content, 42), image_check)
                msg = self.request(content)
                chat = HorseChat(self.bot)
                reality = RealityCheck(self.bot)
                with patch("horsie.horse_chat.chat_completion", AsyncMock(return_value="Neigh!")) as api, patch.object(reality, "target", AsyncMock(side_effect=CheckError("no media"))) as target:
                    await reality.on_message(msg)
                    await chat.on_message(msg)
                self.assertEqual(api.await_count, int(not image_check))
                self.assertEqual(target.await_count, int(image_check))
                msg.reply.assert_awaited_once()

    async def test_reply_continues_own_conversation_only(self):
        with patch("horsie.horse_chat.chat_completion", AsyncMock(return_value="Hello!")) as api:
            first = self.request()
            await self.cog.on_message(first)
            self.cog.last_success.clear()
            followup = self.request("tell me more", id=101)
            followup.reference = NS(message_id=1100)
            await self.cog.on_message(followup)
            payload = api.await_args.args[0]
            self.assertEqual([item["role"] for item in payload], ["system", "user", "assistant", "user"])
            other = self.request("tell me too")
            other.author.id = 8
            other.reference = NS(message_id=1100)
            await self.cog.on_message(other)
            other.reply.assert_not_awaited()
            other.content = "<@42> hello too"
            await self.cog.on_message(other)
            self.assertEqual(len(api.await_args.args[0]), 2)
            other.channel.id = 21
            await self.cog.on_message(other)
            # User cooldown also applies when switching channels.
            self.assertEqual(api.await_count, 3)
            self.cog.last_success.clear()
            await self.cog.on_message(other)
            self.assertEqual(len(api.await_args.args[0]), 2)
            self.assertFalse(first.reply.await_args.kwargs["allowed_mentions"].everyone)

    async def test_expiry_and_bounded_history(self):
        with patch("horsie.horse_chat.chat_completion", AsyncMock(return_value="hello")) as api:
            for number in range(9):
                self.cog.last_success.clear()
                await self.cog.on_message(self.request(id=number))
            state = self.cog.sessions[(1, 20, 7)]
            self.assertEqual(len(state["messages"]), 12)
            state["updated"] -= TTL + 1
            old_reply = self.request("more")
            old_reply.reference = NS(message_id=1008)
            await self.cog.on_message(old_reply)
            old_reply.reply.assert_not_awaited()
            self.cog.last_success.clear()
            await self.cog.on_message(self.request())
            self.assertEqual(len(api.await_args.args[0]), 2)

    async def test_ignores_bots_dms_webhooks_and_uninvited_messages(self):
        cases = [self.request("hello"), self.request("<@99> hello")]
        for field, value in [("author", NS(id=7, bot=True)), ("guild", None), ("webhook_id", 1)]:
            msg = self.request()
            setattr(msg, field, value)
            cases.append(msg)
        with patch("horsie.horse_chat.chat_completion", AsyncMock()) as api:
            for msg in cases:
                await self.cog.on_message(msg)
                msg.reply.assert_not_awaited()
            api.assert_not_awaited()

    async def test_failures_release_slot_and_allow_retry(self):
        for error in [CheckError("unavailable"), asyncio.TimeoutError(), ValueError()]:
            with patch("horsie.horse_chat.chat_completion", AsyncMock(side_effect=error)):
                await self.cog.on_message(self.request())
            self.assertFalse(self.cog.active)
            self.assertFalse(self.cog.sessions)
            self.assertFalse(self.cog.last_success)
        with patch("horsie.horse_chat.chat_completion", AsyncMock(return_value="hello")) as api:
            await self.cog.on_message(self.request())
            await self.cog.on_message(self.request())
            api.assert_awaited_once()

    async def test_quota_pause_prevents_more_api_calls(self):
        with patch("horsie.horse_chat.chat_completion", AsyncMock(side_effect=QuotaError(60))) as api:
            await self.cog.on_message(self.request())
            await self.cog.on_message(self.request())
            api.assert_awaited_once()
            self.assertFalse(self.cog.active)

    async def test_busy_and_missing_key_do_not_call_api(self):
        with patch("horsie.horse_chat.chat_completion", AsyncMock()) as api:
            with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
                await self.cog.on_message(self.request())
            self.cog.active.add((1, 20, 7))
            await self.cog.on_message(self.request())
            self.cog.active = {(1, 20, i) for i in range(10, 13)}
            await self.cog.on_message(self.request())
            api.assert_not_awaited()


class ChatApiTests(unittest.IsolatedAsyncioTestCase):
    async def call_api(self, status, body, headers=None):
        response = NS(status=status, json=AsyncMock(return_value=body), headers=headers or {})
        request = MagicMock()
        request.__aenter__ = AsyncMock(return_value=response)
        request.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post.return_value = request
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=session)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "GROQ_CHAT_MODEL": "chosen-model"}), patch("horsie.horse_chat.aiohttp.ClientSession", return_value=client):
            answer = await chat_completion([{"role": "user", "content": "hello"}])
        return answer, session.post.call_args.kwargs

    async def test_payload_and_plain_text_response(self):
        answer, kwargs = await self.call_api(200, {"choices": [{"message": {"content": " Hello! "}}]})
        self.assertEqual(answer, "Hello!")
        self.assertEqual(kwargs["json"]["model"], "chosen-model")
        self.assertEqual(kwargs["json"]["max_completion_tokens"], 500)
        self.assertFalse(kwargs["allow_redirects"])

    async def test_invalid_responses_and_http_errors_are_friendly(self):
        for body in [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}]:
            with self.assertRaises(CheckError):
                await self.call_api(200, body)
        for status in [401, 403, 404, 500]:
            with self.assertRaises(CheckError):
                await self.call_api(status, {})

    async def test_quota_delay_uses_provider_header_or_body(self):
        for headers, body, seconds in [({"Retry-After": "42"}, {}, 42), ({}, {"error": {"message": "try again in 2m"}}, 120)]:
            with self.assertRaises(QuotaError) as caught:
                await self.call_api(429, body, headers)
            self.assertEqual(caught.exception.seconds, seconds)
