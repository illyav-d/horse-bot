import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

from horsie import chatgpt_fallback as fallback
from scripts.chatgpt_login import authorization
from urllib.parse import parse_qs, urlsplit


class ChatGPTTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "auth.json"
        env = patch.dict(os.environ, {"HORSE_CHATGPT_AUTH_FILE": str(self.path), "CHATGPT_LAST_RESORT": "true",
                                     "CHATGPT_REQUIRE_USAGE_GUARD": "true",
                                     "HORSE_CHATGPT_CONTROLS_FILE": str(self.path.with_name("controls.json"))})
        env.start()
        self.addCleanup(env.stop)
        pause = patch.object(fallback, "blocked_until", 0)
        pause.start()
        self.addCleanup(pause.stop)

    def record(self):
        return dict(issuer=fallback.ISSUER, subject="test-account", client_id="oaiapp_test", ext_agent_host_id="urn:uuid:test",
                    access_token="private-access", refresh_token="private-refresh", scopes=["chatgpt.tokens.use.direct"],
                    expires_at=time.time() + 3600, model="account-selected-model")

    def snapshot(self, percent=74):
        return dict(source="verified-chatgpt-plan", subject="test-account", used_percent=percent,
                    observed_at=time.time(), reset_at=time.time() + 3600)

    async def test_75_percent_unknown_stale_and_invalid_usage_never_make_requests(self):
        fallback.save_auth(self.path, self.record())
        bad = [None, self.snapshot(75), self.snapshot(90), self.snapshot(float("nan")),
               {**self.snapshot(), "observed_at": time.time() - 16},
               {**self.snapshot(), "source": "local-token-estimate"}]
        with patch.object(fallback.aiohttp, "ClientSession") as session:
            for snapshot in bad:
                with self.assertRaises(fallback.ChatGPTError):
                    await fallback.completion([], snapshot)
            session.assert_not_called()
        self.assertTrue(fallback.usage_admitted(self.snapshot(74.99)))

    async def test_credentials_roundtrip_is_separate_and_protected(self):
        record = self.record()
        fallback.save_auth(self.path, record)
        self.assertEqual(fallback.load_auth(self.path), record)
        if os.name == "nt":
            self.assertNotIn("private-access", self.path.read_text())
        else:
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    async def test_payload_contains_only_supplied_discord_text_and_no_private_profile_or_tools(self):
        messages = [{"role": "system", "content": "Horsie personality"},
                    {"role": "user", "content": "Race tonight?", "private_profile": "weight diet calories"},
                    {"role": "tool", "content": "private profile tool output"}]
        payload = fallback.response_payload(messages, "selected")
        self.assertEqual(payload["input"], [{"role": "user", "content": "Race tonight?"}])
        self.assertEqual(set(payload), {"model", "instructions", "input", "store", "stream"})
        self.assertFalse(payload["store"])
        self.assertTrue(payload["stream"])
        self.assertIn("Horsie personality", payload["instructions"])
        self.assertIn("cannot access", payload["instructions"])
        self.assertNotIn("private_profile", json.dumps(payload))
        self.assertNotIn("private profile tool output", json.dumps(payload))

    async def test_signin_uses_own_public_client_and_no_history_scopes(self):
        url, state, nonce, verifier = authorization("urn:uuid:test", "http://127.0.0.1:12345/auth/callback")
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["client_id"], ["dynamic_agent_client"])
        self.assertEqual(query["agent_name_hint"], ["Horsie"])
        self.assertEqual(query["state"], [state])
        self.assertEqual(query["nonce"], [nonce])
        self.assertIn("chatgpt.tokens.use.direct", query["scope"][0])
        self.assertNotIn("history", query["scope"][0])
        self.assertNotIn(verifier, url)

    async def test_bootstrap_keeps_latest_rotated_credentials_and_has_a_distinct_host(self):
        import base64
        seed = base64.b64encode(json.dumps(self.record()).encode()).decode()
        with patch.dict(os.environ, {"HORSE_CHATGPT_AUTH_BOOTSTRAP": seed}):
            fallback.bootstrap_auth()
            loaded = fallback.load_auth(self.path)
            self.assertNotEqual(loaded["ext_agent_host_id"], self.record()["ext_agent_host_id"])
            self.assertEqual(loaded["access_token"], "private-access")
            loaded["refresh_token"] = "latest-rotated-token"
            fallback.save_auth(self.path, loaded)
            fallback.bootstrap_auth()
            self.assertEqual(fallback.load_auth(self.path)["refresh_token"], "latest-rotated-token")

    async def test_incomplete_stream_never_sends_partial_text(self):
        fallback.save_auth(self.path, self.record())
        async def lines():
            yield b'data: {"type":"response.output_text.delta","delta":"partial"}\n'
            yield b'\n'
        response = NS(status=200, content=lines())
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post.return_value = context
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=session)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(fallback.aiohttp, "ClientSession", return_value=client), \
                patch.object(fallback, "record_api_usage", AsyncMock()) as usage:
            with self.assertRaises(fallback.ChatGPTError):
                await fallback.completion([{ "role": "user", "content": "hello"}], self.snapshot())
            self.assertEqual(usage.await_args.args[2], 0)

    async def test_completed_stream_counts_tokens_without_saving_account_data_in_usage(self):
        fallback.save_auth(self.path, self.record())
        result = {"type": "response.completed", "response": {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "Bring carrots!"}]}],
            "usage": {"input_tokens": 100, "output_tokens": 20}}}
        async def lines():
            yield ("data: " + json.dumps(result) + "\n").encode()
            yield b'\n'
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=NS(status=200, content=lines()))
        context.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.post.return_value = context
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=session)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch.object(fallback.aiohttp, "ClientSession", return_value=client), \
                patch.object(fallback, "record_api_usage", AsyncMock()) as usage:
            self.assertEqual(await fallback.completion([], self.snapshot()), "Bring carrots!")
            self.assertEqual(usage.await_args.args[3]["usage"]["prompt_tokens"], 100)
            self.assertNotIn("private-access", str(usage.await_args))

    async def test_owner_can_explicitly_waive_percentage_guard_without_waiving_signin(self):
        self.assertTrue(fallback.require_usage_guard())
        with patch.dict(os.environ, {"CHATGPT_REQUIRE_USAGE_GUARD": "false"}):
            self.assertFalse(fallback.require_usage_guard())
            with patch.object(fallback, "access_record", AsyncMock(side_effect=fallback.ChatGPTError("No sign-in"))) as access:
                # Enabled requires this tool's own credential file or bootstrap.
                self.assertFalse(fallback.enabled())
                with self.assertRaises(fallback.ChatGPTError):
                    await fallback.completion([])
                access.assert_not_awaited()

    async def test_switch_off_blocks_requests_and_switching_during_refresh_blocks_send(self):
        fallback.save_auth(self.path, self.record())
        fallback.controls().update(enabled=False)
        with patch.object(fallback.aiohttp, "ClientSession") as session:
            with self.assertRaises(fallback.ChatGPTError):
                await fallback.completion([], self.snapshot())
            session.assert_not_called()
        fallback.controls().update(enabled=True)
        async def refresh(session):
            fallback.controls().update(enabled=False)
            return self.record()
        with patch.object(fallback, "access_record", side_effect=refresh), \
                patch.object(fallback, "record_api_usage", AsyncMock()) as usage:
            with self.assertRaisesRegex(fallback.ChatGPTError, "switched off"):
                await fallback.completion([], self.snapshot())
            usage.assert_not_awaited()
