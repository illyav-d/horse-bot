import asyncio
import json
import os
import tempfile
import unittest
import aiohttp
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

from horsie.ai_usage import UsageLedger, groq_request


NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
BODY = {"usage": {"prompt_tokens": 100, "completion_tokens": 20,
                  "prompt_tokens_details": {"cached_tokens": 30}}}


class UsageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "usage.json"
        self.ledger = UsageLedger(self.path)

    async def test_retries_failures_and_features_survive_restart_without_content(self):
        self.ledger.record("chat", "qwen", 200, {**BODY, "choices": [{"message": {"content": "private chat"}}]}, now=NOW)
        self.ledger.record("chat", "qwen", 200, BODY, retry=True, now=NOW)
        self.ledger.record("summary", "qwen", 429, {"error": "secret error"}, now=NOW)
        self.ledger.record("image", "qwen", 0, now=NOW)
        restored = UsageLedger(self.path)
        report = restored.report(NOW)
        self.assertIn("240 reported tokens: 200 input + 40 output", report)
        self.assertIn("4 API attempts, including 1 retries; 2 errors (1 rate limits)", report)
        self.assertIn("2 attempts today had no token counts", report)
        self.assertIn("60 cached input tokens", report)
        raw = self.path.read_text()
        self.assertNotIn("private chat", raw)
        self.assertNotIn("secret error", raw)

    async def test_concurrent_updates_are_not_lost(self):
        await asyncio.gather(*(asyncio.to_thread(self.ledger.record, "chat", "qwen", 200, BODY, now=NOW)
                               for _ in range(30)))
        self.assertIn("3,600 reported tokens", UsageLedger(self.path).report(NOW))

    async def test_utc_days_week_totals_and_retention(self):
        for age in (40, 8, 6, 1, 0):
            self.ledger.record("chat", "qwen", 200, BODY, now=NOW - timedelta(days=age))
        report = self.ledger.report(NOW)
        self.assertIn("Last 7 UTC days: 360 reported tokens", report)
        self.assertEqual(len(self.ledger.days), 4)
        self.assertIn("120 reported tokens", report)

    async def test_storage_failure_retains_live_totals_and_retries(self):
        with patch("horsie.ai_usage.write_json", side_effect=OSError("disk unavailable")):
            self.ledger.record("chat", "qwen", 200, BODY, now=NOW)
        self.assertIn("may not survive a restart", self.ledger.report(NOW))
        self.ledger.record("chat", "qwen", 200, BODY, now=NOW)
        self.assertIn("240 reported tokens", UsageLedger(self.path).report(NOW))

    async def test_bad_usage_is_reported_as_unknown_and_corruption_is_visible(self):
        self.path.write_text("not JSON")
        ledger = UsageLedger(self.path)
        ledger.record("chat", "qwen", 200, {"usage": {"prompt_tokens": -1, "completion_tokens": "20"}}, now=NOW)
        report = ledger.report(NOW)
        self.assertIn("0 reported tokens", report)
        self.assertIn("1 attempts today had no token counts", report)
        self.assertIn("historical totals are incomplete", report)

    async def test_http_attempts_are_measured_even_for_empty_answers_and_network_errors(self):
        response = NS(status=200, headers={}, json=AsyncMock(return_value={**BODY, "choices": []}))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post.return_value = context
        with patch.dict(os.environ, {"GROQ_API_KEY": "secret"}), \
                patch("horsie.ai_usage.record_api_usage", AsyncMock()) as record:
            await groq_request(session, "qwen", {}, "chat", True)
            record.assert_awaited_once_with("chat", "qwen", 200, {**BODY, "choices": []}, True)
            context.__aenter__.side_effect = asyncio.TimeoutError()
            with self.assertRaises(asyncio.TimeoutError):
                await groq_request(session, "qwen", {}, "image")
            self.assertEqual(record.await_args.args, ("image", "qwen", 0, None, False))

    async def test_rate_limit_without_json_still_keeps_retry_header_and_records_attempt(self):
        response = NS(status=429, headers={"Retry-After": "42"},
                      json=AsyncMock(side_effect=aiohttp.ClientPayloadError()))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post.return_value = context
        with patch.dict(os.environ, {"GROQ_API_KEY": "secret"}), \
                patch("horsie.ai_usage.record_api_usage", AsyncMock()) as record:
            self.assertEqual(await groq_request(session, "qwen", {}, "chat"),
                             (429, {}, {"Retry-After": "42"}))
            record.assert_awaited_once_with("chat", "qwen", 429, {}, False)
