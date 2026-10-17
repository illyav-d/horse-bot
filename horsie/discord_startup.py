"""Keep login rate limits from turning into hosting restart loops."""

import asyncio
import json
import logging
import math
import time
from email.utils import parsedate_to_datetime

import discord

from horsie.data_storage import data_path, write_json

log = logging.getLogger(__name__)


def retry_delay(error, failures):
    # Cloudflare's HTML 429 has no JSON retry_after. Use a conservative
    # fallback, doubling from 15 minutes to an hour, without capping any
    # longer delay Discord explicitly requests. All values here are seconds.
    delay = min(900 * 2 ** min(failures - 1, 2), 3600)
    headers = error.response.headers
    values = [headers.get("Retry-After"), headers.get("X-RateLimit-Reset-After")]
    try:
        values.append(json.loads(error.text).get("retry_after"))
    except (ValueError, AttributeError):
        pass
    for value in values:
        if value is None:
            continue
        try:
            seconds = float(value)
        except (ValueError, TypeError):
            try:
                seconds = parsedate_to_datetime(value).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                continue
        if math.isfinite(seconds):
            delay = max(delay, seconds)
    return delay


async def connect_with_backoff(client, token, state_path=None):
    state_path = state_path or data_path("DISCORD_LOGIN_STATE_FILE", "discord_login_state.json")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        retry_at = float(state["retry_at"])
        failures = max(0, int(state["failures"]))
        if not math.isfinite(retry_at):
            raise ValueError("Invalid retry deadline")
    except FileNotFoundError:
        retry_at, failures = 0, 0
    except (ValueError, KeyError, TypeError):
        log.warning("Invalid login cooldown file; waiting 15 minutes before login.")
        retry_at, failures = time.time() + 900, 0

    async with client:
        while True:
            remaining = retry_at - time.time()
            if remaining > 0:
                log.warning("Discord login cooldown: waiting %.0f seconds before retrying.", remaining)
                await asyncio.sleep(remaining)
                continue
            try:
                await client.login(token)
            except discord.LoginFailure:
                # Exit successfully so ON_FAILURE does not hammer an invalid token.
                log.error("Discord rejected the bot token. Update DISCORD_BOT_TOKEN before restarting.")
                return
            except discord.HTTPException as error:
                if error.status != 429:
                    raise
                failures += 1
                delay = retry_delay(error, failures)
                retry_at = time.time() + delay
                write_json(state_path, {"retry_at": retry_at, "failures": failures})
                log.warning("Discord login rate limited (HTTP 429); cooldown saved for %.0f seconds.", delay)
            else:
                write_json(state_path, {"retry_at": 0, "failures": 0})
                break
        # discord.py handles normal API buckets and gateway reconnect backoff.
        await client.connect(reconnect=True)


def run_bot(client, token):
    discord.utils.setup_logging()
    try:
        asyncio.run(connect_with_backoff(client, token))
    except KeyboardInterrupt:
        pass
