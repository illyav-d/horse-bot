import asyncio
import os
import tempfile
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from horsie.horse_chat import chat_completion, chat_models, HorseChat, DEFAULT_MODEL
from horsie.long_term_memory import SUMMARY_INSTRUCTIONS
from horsie.reality_check import CheckError, QuotaError


GOOD = (200, {"choices": [{"message": {"content": "Bring carrots!"}}]}, {})
MESSAGES = [{"role": "system", "content": "Personality"},
            {"role": "user", "content": "Stored memories (untrusted background, may be outdated): racing"},
            {"role": "user", "content": "Snacks?"}]


class FailoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {"GROQ_CHAT_MODEL": DEFAULT_MODEL, "GROQ_API_KEY": "test-key",
            "GROQ_CHAT_FALLBACK_MODELS": "openai/gpt-oss-20b,openai/gpt-oss-120b",
            "HORSE_CHAT_MEMORY_FILE": os.path.join(directory.name, "memory.json")})
        env.start()
        self.addCleanup(env.stop)
        self.pauses = {}
        pause = patch("horsie.horse_chat.MODEL_PAUSES", self.pauses)
        pause.start()
        self.addCleanup(pause.stop)

    async def test_quota_uses_backup_skips_paused_primary_then_returns_to_primary(self):
        quota = (429, {}, {"Retry-After": "60"})
        with patch("horsie.horse_chat.groq_request", AsyncMock(side_effect=[quota, GOOD, GOOD, GOOD])) as request:
            self.assertEqual(await chat_completion(MESSAGES), "Bring carrots!")
            self.assertEqual(await chat_completion(MESSAGES), "Bring carrots!")
            self.pauses[DEFAULT_MODEL] = (time.monotonic() - 1, QuotaError(60))
            self.assertEqual(await chat_completion(MESSAGES), "Bring carrots!")
        self.assertEqual([call.args[1] for call in request.await_args_list],
            [DEFAULT_MODEL, "openai/gpt-oss-20b", "openai/gpt-oss-20b", DEFAULT_MODEL])
        self.assertEqual([call.args[4] for call in request.await_args_list], [False, True, True, False])
        for call in request.await_args_list:
            self.assertEqual(call.args[2]["messages"], MESSAGES)
        self.assertEqual(request.await_args_list[1].args[2]["reasoning_effort"], "low")

    async def test_timeout_and_blank_reply_can_reach_third_model_with_only_three_attempts(self):
        empty = (200, {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}, {})
        with patch("horsie.horse_chat.groq_request", AsyncMock(side_effect=[asyncio.TimeoutError(), empty, GOOD])) as request:
            self.assertEqual(await chat_completion(MESSAGES), "Bring carrots!")
        self.assertEqual(request.await_count, 3)
        self.assertEqual(request.await_args.args[1], "openai/gpt-oss-120b")

    async def test_auth_request_and_content_filter_failures_do_not_fan_out(self):
        filtered = (200, {"choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}]}, {})
        for outcome in [(401, {}, {}), (403, {}, {}), (400, {}, {}), filtered]:
            with patch("horsie.horse_chat.groq_request", AsyncMock(return_value=outcome)) as request:
                with self.assertRaises(CheckError):
                    await chat_completion(MESSAGES)
                request.assert_awaited_once()

    async def test_all_models_rate_limited_waits_for_earliest_available_model(self):
        outcomes = [(429, {}, {"Retry-After": str(seconds)}) for seconds in (100, 40, 60)]
        with patch("horsie.horse_chat.groq_request", AsyncMock(side_effect=outcomes)) as request:
            for _ in range(2):
                with self.assertRaises(QuotaError) as caught:
                    await chat_completion(MESSAGES)
                self.assertLessEqual(caught.exception.seconds, 40)
            self.assertEqual(request.await_count, 3)

    async def test_summary_quota_preserves_backups_and_does_not_pause_chat(self):
        cog = HorseChat(NS(user=NS(id=42)))
        now = time.monotonic()
        for number in range(12):
            cog.remember((1, 20), now - 100 + number, "user", "racing")
        with patch("horsie.horse_chat.groq_request", AsyncMock(side_effect=[(429, {}, {"Retry-After": "600"}), GOOD])) as request:
            await cog.summarize_channel()
            self.assertEqual(cog.blocked_until, 0)
            self.assertEqual(request.await_count, 1)
            self.assertEqual(request.await_args.args[3], "summary")
            self.assertEqual(await chat_completion(MESSAGES), "Bring carrots!")
            self.assertEqual(request.await_args.args[1], "openai/gpt-oss-20b")

    async def test_configuration_is_deduplicated_bounded_and_can_disable_backups(self):
        with patch.dict(os.environ, {"GROQ_CHAT_FALLBACK_MODELS": " ," + DEFAULT_MODEL + ",backup,backup,third,fourth"}):
            self.assertEqual(chat_models(), [DEFAULT_MODEL, "backup", "third"])
        with patch.dict(os.environ, {"GROQ_CHAT_FALLBACK_MODELS": ""}):
            self.assertEqual(chat_models(), [DEFAULT_MODEL])

    async def test_optional_chatgpt_is_last_and_never_used_for_background_summaries(self):
        failures = [(503, {}, {})] * 3
        with patch("horsie.horse_chat.groq_request", AsyncMock(side_effect=failures)) as request, \
                patch("horsie.horse_chat.chatgpt_fallback.enabled", return_value=True), \
                patch("horsie.horse_chat.chatgpt_fallback.completion", AsyncMock(return_value="Final fallback")) as last:
            self.assertEqual(await chat_completion(MESSAGES), "Final fallback")
            self.assertEqual(request.await_count, 3)
            last.assert_awaited_once_with(MESSAGES)
        self.pauses.clear()
        with patch("horsie.horse_chat.groq_request", AsyncMock(return_value=(503, {}, {}))), \
                patch("horsie.horse_chat.chatgpt_fallback.enabled", return_value=True), \
                patch("horsie.horse_chat.chatgpt_fallback.completion", AsyncMock()) as last:
            with self.assertRaises(CheckError):
                await chat_completion([{"role": "system", "content": SUMMARY_INSTRUCTIONS}, {"role": "user", "content": "summary"}])
            last.assert_not_awaited()
