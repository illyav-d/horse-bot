import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from bot_text import line
from horse_reactions import HorseReactions, MACARONI_IMAGE


class ReactionTests(unittest.IsolatedAsyncioTestCase):
    def message(self, text, bot=False, webhook=None):
        return SimpleNamespace(
            content=text, author=SimpleNamespace(bot=bot), webhook_id=webhook,
            channel=SimpleNamespace(id=123, send=AsyncMock()),
        )

    async def test_phrase_variants_upload_the_bundled_image(self):
        for text in ["macaroni horse", "MACARONI HORSE!", "please show macaroni   horse 🍝"]:
            with self.subTest(text=text):
                message = self.message(text)

                async def sent(*args, **kwargs):
                    image = kwargs["file"]
                    self.assertEqual(image.filename, "macaroni_horse.jpg")
                    self.assertEqual(image.fp.read(3), b"\xff\xd8\xff")
                    self.assertFalse(kwargs["allowed_mentions"].everyone)

                message.channel.send.side_effect = sent
                await HorseReactions().on_message(message)
                message.channel.send.assert_awaited_once()

    async def test_unrelated_messages_and_other_bots_are_ignored(self):
        for text, bot, webhook in [
            ("macaroni", False, None), ("horse", False, None),
            ("macaroni horses", False, None), ("premacaroni horse", False, None),
            ("!horse", False, None), ("macaroni horse", True, None),
            ("macaroni horse", False, 42),
            ("shutup chelseas", False, None), ("shutup chelsea", True, None),
            ("shutup chelsea", False, 42),
        ]:
            message = self.message(text, bot=bot, webhook=webhook)
            await HorseReactions().on_message(message)
            message.channel.send.assert_not_awaited()

    async def test_rat_phrase_uploads_image_with_caption(self):
        for text in ["shutup chelsea", "SHUTUP CHELSEA!", "please shut up   Chelsea"]:
            with self.subTest(text=text):
                message = self.message(text)

                async def sent(*args, **kwargs):
                    self.assertEqual(args, ("take this rat and relax",))
                    self.assertEqual(kwargs["file"].filename, "rat_throw.jpg")
                    self.assertEqual(kwargs["file"].fp.read(3), b"\xff\xd8\xff")

                message.channel.send.side_effect = sent
                await HorseReactions().on_message(message)
                message.channel.send.assert_awaited_once()

    async def test_missing_asset_does_not_raise(self):
        message = self.message("macaroni horse")
        with patch("horse_reactions.MACARONI_IMAGE", MACARONI_IMAGE.parent / "missing-test-image.jpg"), patch("builtins.print"):
            await HorseReactions().on_message(message)
        message.channel.send.assert_not_awaited()

    async def test_missing_upload_permission_does_not_raise(self):
        message = self.message("macaroni horse")
        message.channel.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "denied")
        with patch("builtins.print"):
            await HorseReactions().on_message(message)
        message.channel.send.assert_awaited_once()

    async def test_listener_registered_without_replacing_command_handler(self):
        import horse_bot
        from discord.ext import commands
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
        async with bot:
            with patch.object(horse_bot, "bot", bot):
                await horse_bot.setup_hook()
            self.assertTrue(bot.extra_events.get("on_message"))
            self.assertIn("process_commands", bot.on_message.__func__.__code__.co_names)
            self.assertIsNotNone(bot.get_command("horsearticle"))


class TextTests(unittest.TestCase):
    def test_variant_selection_avoids_immediate_repeats(self):
        results = [line("horse_caption") for _ in range(30)]
        self.assertTrue(all(a != b for a, b in zip(results, results[1:])))

    def test_variable_values_stay_literal(self):
        self.assertIn("**42**", line("carrots_self", count=42))


if __name__ == "__main__":
    unittest.main()
