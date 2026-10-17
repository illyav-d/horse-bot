"""Message reactions that leave the normal command handler intact."""

import re
from contextlib import closing

import discord
from discord.ext import commands

from horsie.bot_text import line
from horsie.data_storage import ASSETS_DIR


MACARONI_IMAGE = ASSETS_DIR / "macaroni_horse.jpg"
MACARONI_PATTERN = re.compile(r"\bmacaroni\s+horse\b", re.IGNORECASE)
RAT_IMAGE = ASSETS_DIR / "rat_throw.jpg"
RAT_VIDEO = ASSETS_DIR / "rat.mp4"
RAT_VIDEO_PATTERN = re.compile(r"(?<!\w)!rat\b|\bi\s+love\s+rat\b", re.IGNORECASE)
RAT_PATTERN = re.compile(r"\bshut\s*up\s+chelsea\b", re.IGNORECASE)


class HorseReactions(commands.Cog):
    @commands.command(name="rat")
    async def rat(self, ctx):
        """Post the rat video (sent by the shared message listener)."""
        # The listener also supports phrases and embedded !rat triggers.
        # Register the command so normal !rat use is recognized without
        # uploading a second copy of the video.
        pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or getattr(message, "webhook_id", None):
            return
        if RAT_VIDEO_PATTERN.search(message.content):
            image_path, filename, caption = RAT_VIDEO, "rat.mp4", None
        elif RAT_PATTERN.search(message.content):
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
