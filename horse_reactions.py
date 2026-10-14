"""Message reactions that leave the normal command handler intact."""

import re
from contextlib import closing
from pathlib import Path

import discord
from discord.ext import commands

from bot_text import line


MACARONI_IMAGE = Path(__file__).resolve().parent / "assets" / "macaroni_horse.jpg"
MACARONI_PATTERN = re.compile(r"\bmacaroni\s+horse\b", re.IGNORECASE)
RAT_IMAGE = Path(__file__).resolve().parent / "assets" / "rat_throw.jpg"
RAT_PATTERN = re.compile(r"\bshut\s*up\s+chelsea\b", re.IGNORECASE)


class HorseReactions(commands.Cog):
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or getattr(message, "webhook_id", None):
            return
        if RAT_PATTERN.search(message.content):
            image_path, filename, caption = RAT_IMAGE, "rat_throw.jpg", "take this rat and relax"
        elif MACARONI_PATTERN.search(message.content):
            image_path, filename, caption = MACARONI_IMAGE, "macaroni_horse.jpg", line("macaroni")
        else:
            return
        try:
            with closing(discord.File(str(image_path), filename=filename)) as image:
                await message.channel.send(
                    caption, file=image,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except (OSError, discord.HTTPException) as error:
            print(f"Could not post {filename} in channel {message.channel.id}: {error}")
