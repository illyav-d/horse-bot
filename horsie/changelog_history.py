"""Keep rapid deployments from repeating the same Discord changelog entries."""

import json
from datetime import datetime, timedelta, timezone

import discord

from horsie.data_storage import write_json


class ChangelogHistory:
    def __init__(self, path):
        self.path = path
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            self.state = state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            self.state = {}

    async def select(self, guild_id, channel, bot_id, entries, now):
        previous = self.state.get(str(guild_id))
        if isinstance(previous, dict):
            timestamp = previous.get("posted_at")
            known = previous.get("entries")
            if isinstance(timestamp, (int, float)) and isinstance(known, list) and all(isinstance(item, str) for item in known):
                if 0 <= now - timestamp < 3600:
                    return [item for item in entries if item not in known], known
                return list(entries), []

        # Bootstrap from Discord on the first deployment with this feature.
        # Only the bot's own changelog embeds count; ordinary messages do not.
        known = []
        if bot_id is not None:
            cutoff = datetime.fromtimestamp(now, timezone.utc) - timedelta(hours=1)
            try:
                async for message in channel.history(limit=None, after=cutoff, oldest_first=False):
                    if message.author.id != bot_id or message.webhook_id:
                        continue
                    for embed in message.embeds:
                        if not (embed.title or "").startswith("Horsie Bot v"):
                            continue
                        if not (embed.description or "").startswith("**Changelog"):
                            continue
                        known.extend(line[2:] for line in embed.description.splitlines() if line.startswith("- "))
            except discord.HTTPException as error:
                print(f"Could not read recent changelog in server {guild_id}: {error}")
        return [item for item in entries if item not in known], known

    def record(self, guild_id, entries, now):
        self.state[str(guild_id)] = {
            "posted_at": now,
            "entries": list(dict.fromkeys(entries)),
        }
        write_json(self.path, self.state)
