import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from horsie.discord_startup import connect_with_backoff, retry_delay


def limited(headers=None, body="<html>Cloudflare 1015</html>"):
    return discord.HTTPException(
        SimpleNamespace(status=429, reason="Too Many Requests", headers=headers or {}), body
    )


class LoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_cooldown_survives_restart_and_escalates_until_login(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "login.json"
            clock = [1000.0]
            client = AsyncMock()
            client.login.side_effect = [limited(), limited(), None]

            async def sleep(seconds):
                clock[0] += seconds

            with patch("horsie.discord_startup.time.time", side_effect=lambda: clock[0]), patch(
                "horsie.discord_startup.asyncio.sleep", side_effect=sleep
            ) as wait:
                await connect_with_backoff(client, "test-token", path)
                self.assertEqual([call.args[0] for call in wait.await_args_list], [900, 1800])
                client.connect.assert_awaited_once_with(reconnect=True)
                self.assertEqual(json.loads(path.read_text())["failures"], 0)

                client.reset_mock()
                client.login.side_effect = None
                path.write_text(json.dumps({"retry_at": clock[0] + 700, "failures": 2}))
                await connect_with_backoff(client, "test-token", path)
                self.assertEqual(wait.await_args_list[-1].args, (700,))

    async def test_invalid_token_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            client = AsyncMock()
            client.login.side_effect = discord.LoginFailure("invalid")
            await connect_with_backoff(client, "test-token", Path(directory) / "login.json")
            client.login.assert_awaited_once()
            client.connect.assert_not_awaited()

    async def test_other_http_failures_are_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            client = AsyncMock()
            client.login.side_effect = discord.Forbidden(
                SimpleNamespace(status=403, reason="Forbidden"), "denied"
            )
            with self.assertRaises(discord.Forbidden):
                await connect_with_backoff(client, "test-token", Path(directory) / "login.json")
            client.login.assert_awaited_once()

    def test_retry_delays_honor_server_values_and_html_fallback(self):
        self.assertEqual(retry_delay(limited(), 1), 900)
        self.assertEqual(retry_delay(limited(), 20), 3600)
        self.assertEqual(retry_delay(limited({"Retry-After": "7200"}), 1), 7200)
        self.assertEqual(retry_delay(limited(body='{"retry_after": 5400}'), 1), 5400)
        self.assertEqual(retry_delay(limited({"Retry-After": "invalid"}), 1), 900)
        with patch("horsie.discord_startup.time.time", return_value=0):
            self.assertEqual(retry_delay(limited({"Retry-After": "Thu, 01 Jan 1970 02:00:00 GMT"}), 1), 7200)


if __name__ == "__main__":
    unittest.main()
