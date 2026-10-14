"""Message reactions that leave the normal command handler intact."""

import re
from contextlib import closing
from pathlib import Path

import discord
from discord.ext import commands

from bot_text import line


MACARONI_IMAGE = Path(__file__).resolve().parent / "assets" / "macaroni_horse.jpg"
MACARONI_PATTERN = re.compile(r"\bmacaroni\s+horse\b", re.IGNORECASE)


class HorseReactions(commands.Cog):
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or getattr(message, "webhook_id", None):
            return
        if not MACARONI_PATTERN.search(message.content):
            return
        try:
            with closing(discord.File(str(MACARONI_IMAGE), filename="macaroni_horse.jpg")) as image:
                await message.channel.send(
                    line("macaroni"), file=image,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except (OSError, discord.HTTPException) as error:
            print(f"Could not post macaroni horse in channel {message.channel.id}: {error}")
