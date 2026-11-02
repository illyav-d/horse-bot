import asyncio
import json
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

from horsie.horse_chat import DEFAULT_MODEL, HorseChat, TTL, chat_completion
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

    async def test_shared_channel_context_and_replies_from_any_person(self):
        with patch("horsie.horse_chat.chat_completion", AsyncMock(return_value="Hello!")) as api:
            background = self.request("we are racing tonight", id=90)
            background.author.display_name = "Alice"
            await self.cog.on_message(background)
            api.assert_not_awaited()
            await self.cog.on_message(self.request())
            payload = api.await_args.args[0]
            self.assertIn("we are racing tonight", payload[1]["content"])
            self.assertEqual(json.loads(payload[1]["content"])["speaker"], "Alice")
            other = self.request("tell me too", id=101)
            other.author.id = 8
            other.reference = NS(message_id=1100)
            await self.cog.on_message(other)
            payload = api.await_args.args[0]
            self.assertEqual(api.await_count, 2)
            self.assertEqual(json.loads(payload[-1]["content"])["user_id"], "8")
            self.assertIn("we are racing tonight", str(payload))
            for field in ("channel", "guild"):
                fresh = self.request()
                fresh.author.id = 9
                getattr(fresh, field).id += 1
                self.cog.last_success.clear()
                await self.cog.on_message(fresh)
                self.assertEqual(len(api.await_args.args[0]), 2)

    async def test_expiry_and_bounded_history(self):
        with patch("horsie.horse_chat.chat_completion", AsyncMock(return_value="hello")) as api:
            for number in range(60):
                await self.cog.on_message(self.request("background " + str(number), id=number))
            state = self.cog.sessions[(1, 20)]
            self.assertEqual(len(state["messages"]), 40)
            for entry in state["messages"]:
                entry["at"] -= TTL + 1
            await self.cog.on_message(self.request())
            self.assertEqual(len(api.await_args.args[0]), 2)
            # Expire individual messages even in an otherwise active channel.
            state = self.cog.sessions[(1, 20)]
            state["messages"][0]["at"] -= TTL + 1
            self.cog.prune(asyncio.get_running_loop().time())
            self.assertEqual(len(state["messages"]), 1)

    async def test_passive_messages_arriving_during_reply_are_preserved(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def delayed(messages):
            started.set()
            await finish.wait()
            return "hello"
        with patch("horsie.horse_chat.chat_completion", side_effect=delayed):
            task = asyncio.create_task(self.cog.on_message(self.request()))
            await started.wait()
            passive = self.request("new topic while you think", id=102)
            passive.author.id = 8
            await self.cog.on_message(passive)
            second = self.request("<@42> me too", id=103)
            second.author.id = 9
            await self.cog.on_message(second)
            self.assertIn("still answering", second.reply.await_args.args[0])
            finish.set()
            await task
        self.assertIn("new topic while you think", str(self.cog.sessions[(1, 20)]))
        self.assertFalse(self.cog.active_users)

    async def test_context_size_channel_limit_and_ignored_authors(self):
        for number in range(30):
            await self.cog.on_message(self.request("x" * 4000, id=number))
        state = self.cog.sessions[(1, 20)]
        self.assertLessEqual(sum(len(entry["payload"]["content"]) for entry in state["messages"]), 24000)
        for number in range(140):
            msg = self.request("background")
            msg.channel.id = 100 + number
            await self.cog.on_message(msg)
        self.assertEqual(len(self.cog.sessions), 128)

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
            self.assertTrue(self.cog.sessions)  # Channel messages survive failed AI calls.
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
            self.cog.active.add((1, 20))
            await self.cog.on_message(self.request())
            self.cog.active = {(1, i) for i in range(10, 13)}
            await self.cog.on_message(self.request())
            api.assert_not_awaited()


class ChatApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_and_blank_model_use_available_qwen_without_reasoning(self):
        for value in (None, "", "   "):
            response = NS(status=200, json=AsyncMock(return_value={"choices": [{"message": {"content": "Hello!"}}]}))
            request = MagicMock()
            request.__aenter__ = AsyncMock(return_value=response)
            request.__aexit__ = AsyncMock(return_value=False)
            session = MagicMock()
            session.post.return_value = request
            client = MagicMock()
            client.__aenter__ = AsyncMock(return_value=session)
            client.__aexit__ = AsyncMock(return_value=False)
            env = {"GROQ_API_KEY": "test-key"}
            if value is not None:
                env["GROQ_CHAT_MODEL"] = value
            with patch.dict(os.environ, env, clear=True), patch("horsie.horse_chat.aiohttp.ClientSession", return_value=client):
                await chat_completion([{"role": "user", "content": "hello"}])
            payload = session.post.call_args.kwargs["json"]
            self.assertEqual(payload["model"], DEFAULT_MODEL)
            self.assertEqual(payload["reasoning_effort"], "none")

    async def call_api(self, status, body, headers=None, responses=None):
        response = NS(status=status, json=AsyncMock(return_value=body), headers=headers or {})
        if responses is not None:
            response.json.side_effect = responses
        request = MagicMock()
        request.__aenter__ = AsyncMock(return_value=response)
        request.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post.return_value = request
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=session)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "GROQ_CHAT_MODEL": "chosen-model"}), patch("horsie.horse_chat.aiohttp.ClientSession", return_value=client):
            try:
                answer = await chat_completion([{"role": "user", "content": "hello"}])
            finally:
                self.requests = session.post.call_args_list
        return answer, session.post.call_args.kwargs

    async def test_empty_reply_retries_once_and_preserves_context(self):
        good = {"choices": [{"message": {"content": "Hello!"}, "finish_reason": "stop"}]}
        for content in (None, "", "   "):
            empty = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
            answer, _ = await self.call_api(200, {}, responses=[empty, good])
            self.assertEqual(answer, "Hello!")
            self.assertEqual(len(self.requests), 2)
            self.assertEqual(self.requests[0].kwargs["json"]["messages"], self.requests[1].kwargs["json"]["messages"])

    async def test_empty_length_reply_gets_more_output_budget(self):
        empty = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
        good = {"choices": [{"message": {"content": "Hello!"}}]}
        await self.call_api(200, {}, responses=[empty, good])
        self.assertEqual([request.kwargs["json"]["max_completion_tokens"] for request in self.requests], [500, 1000])

    async def test_empty_replies_stop_after_two_attempts_without_logging_text(self):
        with patch("builtins.print") as log:
            with self.assertRaisesRegex(CheckError, "twice"):
                await self.call_api(200, {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]})
        self.assertEqual(len(self.requests), 2)
        self.assertIn("finish=stop", str(log.call_args_list))
        self.assertNotIn("test-key", str(log.call_args_list))
        self.assertNotIn("hello", str(log.call_args_list))

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
            self.assertEqual(len(self.requests), 1)

    async def test_quota_delay_uses_provider_header_or_body(self):
        for headers, body, seconds in [({"Retry-After": "42"}, {}, 42), ({}, {"error": {"message": "try again in 2m"}}, 120)]:
            with self.assertRaises(QuotaError) as caught:
                await self.call_api(429, body, headers)
            self.assertEqual(caught.exception.seconds, seconds)
