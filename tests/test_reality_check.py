import asyncio
import base64
import io
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import aiohttp
from PIL import Image

from horsie.reality_check import CAUTION, GIF_CAUTION, CheckError, RealityCheck, assess, download_image, image_urls, validate_image_url, PublicImageResolver, gemini_error, request_gemini, gif_parts


def gif_fixture(count=10):
    frames = [Image.new("RGB", (20, 20), (i * 21 % 256, 255 - i * 19 % 256, i * 13 % 256)) for i in range(count)]
    output = io.BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    return output.getvalue()


def message(content="", attachments=None, embeds=None, id=100):
    channel = NS(id=20, fetch_message=AsyncMock(), typing=MagicMock())
    channel.typing.return_value.__aenter__ = AsyncMock()
    channel.typing.return_value.__aexit__ = AsyncMock(return_value=False)
    return NS(content=content, attachments=attachments or [], embeds=embeds or [],
              id=id, jump_url=f"https://discord.com/channels/1/20/{id}", reference=None,
              author=NS(id=7, bot=False), webhook_id=None, guild=NS(id=1),
              channel=channel, reply=AsyncMock(), created_at=discord.utils.utcnow())


def photo(id=90):
    return message(attachments=[NS(content_type="image/png", size=500,
                                  url="https://cdn.discordapp.com/attachments/1/2/test.png")], id=id)


def history(channel, messages):
    async def iterate(**kwargs):
        for msg in messages:
            yield msg
    channel.history = MagicMock(side_effect=iterate)


class RealityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = RealityCheck(NS(user=NS(id=42)))
        self.env = patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_mention_variants_find_image_past_intervening_chat(self):
        for text in ["<@42> is this real?", "is it real <@!42>", "<@42> real or AI?",
                     "<@42> is that AI?", "<@42> if its real"]:
            with self.subTest(text=text):
                cog = RealityCheck(NS(user=NS(id=42)))
                request, image = message(text), photo()
                history(request.channel, [message("hello", id=99), image, photo(id=89)])
                with patch("horsie.reality_check.assess", AsyncMock(return_value="assessment")) as check:
                    await cog.on_message(request)
                self.assertEqual(check.await_args.args[1], [image.attachments[0].url])
                self.assertIn(image.jump_url, request.reply.await_args.args[0])
                self.assertFalse(request.reply.await_args.kwargs["allowed_mentions"].everyone)
                request.channel.history.assert_called_once_with(limit=50, before=request)

    async def test_ignores_unmentioned_other_bots_webhooks_dms_and_unrelated_mentions(self):
        cases = [message("is this real?"), message("<@99> is this real?"),
                 message("<@42> hello"), message("<@42> is this reality?")]
        for field, value in [("author", NS(id=7, bot=True)), ("webhook_id", 8), ("guild", None)]:
            msg = message("<@42> is this real?")
            setattr(msg, field, value)
            cases.append(msg)
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            for msg in cases:
                await self.cog.on_message(msg)
                msg.reply.assert_not_awaited()
            check.assert_not_awaited()

    async def test_reply_is_explicit_and_cannot_cross_channels(self):
        request = message("<@42> is this real?")
        request.reference = NS(channel_id=20, message_id=90)
        request.channel.fetch_message.return_value = photo()
        self.assertEqual((await self.cog.target(request)).id, 90)
        request.reference.channel_id = 999
        with self.assertRaises(CheckError):
            await self.cog.target(request)
        request.channel.fetch_message.assert_awaited_once()

    async def test_attached_request_image_takes_priority(self):
        request = photo()
        self.assertIs(await self.cog.target(request), request)

    async def test_missing_image_and_missing_key_never_call_api(self):
        request = message("<@42> is this real?")
        history(request.channel, [message("just text")])
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            await self.cog.on_message(request)
            self.assertIn("couldn't find", request.reply.await_args.args[0])
            self.assertFalse(self.cog.active_channels)
            with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
                request.author.id = 8
                await self.cog.on_message(request)
            self.assertIn("GEMINI_API_KEY", request.reply.await_args.args[0])
            check.assert_not_awaited()

    async def test_cooldown_and_failure_release_busy_channel(self):
        request = message("<@42> is this real?")
        history(request.channel, [photo()])
        with patch("horsie.reality_check.assess", AsyncMock(side_effect=asyncio.TimeoutError)) as check:
            await self.cog.on_message(request)
            await self.cog.on_message(request)
            check.assert_awaited_once()
        self.assertFalse(self.cog.active_channels)
        self.assertIn("couldn't finish", request.reply.await_args.args[0])

    async def test_deleted_reply_does_not_fall_back(self):
        request = message("<@42> is this real?")
        request.reference = NS(channel_id=20, message_id=90)
        request.channel.fetch_message.side_effect = discord.NotFound(NS(status=404, reason="Gone"), "gone")
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            await self.cog.on_message(request)
            check.assert_not_awaited()
        self.assertFalse(self.cog.active_channels)

    async def test_busy_channel_does_not_start_another_request(self):
        request = message("<@42> is this real?")
        self.cog.active_channels.add(request.channel.id)
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            await self.cog.on_message(request)
            check.assert_not_awaited()
        self.assertIn("already checking", request.reply.await_args.args[0])
        self.assertIn(request.channel.id, self.cog.active_channels)

    def test_links_previews_and_unsupported_files(self):
        direct = message("https://example.com/image.jpg?x=1")
        self.assertEqual(image_urls(direct), [direct.content])
        embed = discord.Embed(type="rich").set_thumbnail(url="https://example.com/image.png")
        self.assertEqual(image_urls(message(embeds=[embed])), ["https://example.com/image.png"])
        self.assertEqual(image_urls(message("https://example.com/clip.gif")), ["https://example.com/clip.gif"])
        self.assertEqual(image_urls(message(attachments=[NS(content_type="image/gif", size=500,
                                                           url="https://example.com/clip.gif")])), ["https://example.com/clip.gif"])
        gif_embed = discord.Embed.from_dict({"type": "gifv", "video": {"url": "https://media.tenor.com/id/tenor.mp4"},
                                            "thumbnail": {"url": "https://media.tenor.com/id/thumbnail.png"}})
        self.assertEqual(image_urls(message(embeds=[gif_embed])), ["https://media.tenor.com/id/tenor.gif"])
        self.assertEqual(image_urls(message(attachments=[NS(content_type="video/mp4")])), [])
        large = photo()
        large.attachments[0].size = 9 * 1024 * 1024
        with self.assertRaises(CheckError):
            image_urls(large)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def call_api(self, status=200, body=None, model=None, mime="image/png", data=b"image bytes"):
        response = MagicMock(status=status)
        response.json = AsyncMock(return_value=body)
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                patch("horsie.reality_check.aiohttp.ClientSession", factory), \
                patch("horsie.reality_check.aiohttp.TCPConnector"), \
                patch("horsie.reality_check.asyncio.sleep", AsyncMock()), \
                patch("horsie.reality_check.download_image", AsyncMock(return_value=(mime, data))):
            if model is None:
                os.environ.pop("REALITY_CHECK_MODEL", None)
            else:
                os.environ["REALITY_CHECK_MODEL"] = model
            answer = await assess("image", ["https://example.com/image.png"])
        expected_model = model or "gemini-3.8-flash"
        self.assertEqual(session.post.call_args.args[0], f"https://generativelanguage.googleapis.com/v1beta/models/{expected_model}:generateContent")
        self.assertEqual(session.post.call_args.kwargs["headers"], {"x-goog-api-key": "test-key"})
        self.assertFalse(session.post.call_args.kwargs["allow_redirects"])
        return answer, session.post.call_args.kwargs["json"]

    async def test_request_and_visible_uncertainty(self):
        body = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{
            "text": '{"verdict":"Inconclusive","reasons":"No reliable clues."}',
        }]}}]}
        answer, payload = await self.call_api(body=body)
        self.assertIn(CAUTION, answer)
        self.assertIn("Inconclusive", answer)
        inline = payload["contents"][0]["parts"][1]["inlineData"]
        self.assertEqual(inline["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(inline["data"]), b"image bytes")
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 2048)

    async def test_api_failures_and_bad_or_incomplete_responses(self):
        for status, body in [(429, {}), (401, {}), (500, {}), (200, {}),
                             (200, {"candidates": []}),
                             (200, {"candidates": [{"finishReason": "MAX_TOKENS"}]}),
                             (200, {"candidates": [{"finishReason": "SAFETY"}]}),
                             (200, {"candidates": [{"finishReason": "STOP", "content": {"parts": []}}]})]:
            with self.subTest(status=status, body=body), self.assertRaises(CheckError):
                await self.call_api(status, body)

    async def test_gif_submits_sampled_jpegs_and_discloses_sampling(self):
        body = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{
            "text": '{"verdict":"Inconclusive","reasons":"Only sampled frames are available."}',
        }]}}]}
        answer, payload = await self.call_api(body=body, mime="image/gif", data=gif_fixture())
        self.assertIn(GIF_CAUTION, answer)
        parts = payload["contents"][0]["parts"]
        images = [part["inlineData"] for part in parts if "inlineData" in part]
        self.assertEqual(len(images), 4)
        self.assertTrue(all(part["mimeType"] == "image/jpeg" for part in images))
        self.assertIn("frame 10 of 10", parts[-2]["text"])

    async def test_combined_size_limit_prevents_api_request(self):
        with patch.dict(os.environ, {"REALITY_CHECK_MODEL": "gemini-3.8-flash"}), \
                patch("horsie.reality_check.MAX_TOTAL_IMAGE_BYTES", 2), \
                patch("horsie.reality_check.download_image", AsyncMock(return_value=("image/png", b"large"))), \
                self.assertRaisesRegex(CheckError, "too large together"):
            await assess("image", ["https://example.com/image.png"])

    async def test_old_model_override_has_clear_error(self):
        with patch.dict(os.environ, {"REALITY_CHECK_MODEL": "gpt-4.1-mini"}), \
                self.assertRaisesRegex(CheckError, "REALITY_CHECK_MODEL"):
            await assess("image", ["https://example.com/image.png"])

    def test_actionable_errors_do_not_expose_google_error_body(self):
        for status, body, expected in [
            (404, {"error": {"message": "Model is no longer available to new users"}}, "REALITY_CHECK_MODEL"),
            (400, {"error": {"message": "API key not valid: secret-key"}}, "GEMINI_API_KEY"),
            (403, {}, "restrictions"), (429, {}, "usage limit"),
            (400, {}, "request settings"), (503, None, "temporarily unavailable"),
        ]:
            with self.subTest(status=status):
                result = str(gemini_error(status, body))
                self.assertIn(expected, result)
                self.assertNotIn("secret-key", result)


class GifTests(unittest.TestCase):
    def test_samples_first_middle_and_last_frames(self):
        parts = gif_parts(gif_fixture())
        labels = [part["text"] for part in parts if "text" in part]
        self.assertEqual([label.split(" of ")[0] for label in labels],
                         ["GIF sampled frame 1", "GIF sampled frame 4", "GIF sampled frame 7", "GIF sampled frame 10"])
        first = Image.open(io.BytesIO(base64.b64decode(parts[1]["inlineData"]["data"])))
        last = Image.open(io.BytesIO(base64.b64decode(parts[-1]["inlineData"]["data"])))
        self.assertNotEqual(first.getpixel((10, 10)), last.getpixel((10, 10)))

    def test_single_frame_gif_is_not_duplicated(self):
        parts = gif_parts(gif_fixture(1))
        self.assertEqual(len(parts), 2)
        self.assertIn("frame 1 of 1", parts[0]["text"])

    def test_invalid_and_excessively_long_gifs_have_helpful_errors(self):
        with self.assertRaises(CheckError):
            gif_parts(b"GIF89anot-valid")
        with self.assertRaisesRegex(CheckError, "too long"):
            gif_parts(gif_fixture(201))


class RetryTests(unittest.IsolatedAsyncioTestCase):
    def session(self, outcomes):
        session = MagicMock()
        contexts = []
        for outcome in outcomes:
            context = MagicMock()
            if isinstance(outcome, Exception):
                context.__aenter__ = AsyncMock(side_effect=outcome)
            else:
                response = NS(status=outcome, json=AsyncMock(return_value={"result": "ok"}))
                context.__aenter__ = AsyncMock(return_value=response)
            context.__aexit__ = AsyncMock(return_value=False)
            contexts.append(context)
        session.post.side_effect = contexts
        return session

    async def call(self, session):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                patch("horsie.reality_check.asyncio.sleep", AsyncMock()) as sleep:
            result = await request_gemini(session, "gemini-3.8-flash", {"images": "same payload"})
        return result, sleep

    async def test_server_failures_recover_without_changing_payload(self):
        session = self.session([503, 502, 200])
        result, sleep = await self.call(session)
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(session.post.call_count, 3)
        self.assertEqual(sleep.await_count, 2)
        self.assertTrue(1 <= sleep.await_args_list[0].args[0] <= 1.3)
        self.assertTrue(2 <= sleep.await_args_list[1].args[0] <= 2.3)
        payloads = [call.kwargs["json"] for call in session.post.call_args_list]
        self.assertTrue(all(payload is payloads[0] for payload in payloads))

    async def test_exhausted_server_failures_stop_after_three_attempts(self):
        session = self.session([503, 503, 503])
        with self.assertRaisesRegex(CheckError, "after three attempts"):
            await self.call(session)
        self.assertEqual(session.post.call_count, 3)

    async def test_configuration_and_quota_errors_are_not_retried(self):
        for status in (400, 401, 403, 404, 429):
            session = self.session([status])
            with self.subTest(status=status), self.assertRaises(CheckError):
                await self.call(session)
            self.assertEqual(session.post.call_count, 1)

    async def test_connection_failure_and_timeout_can_recover(self):
        session = self.session([aiohttp.ClientConnectionError(), asyncio.TimeoutError(), 200])
        result, _ = await self.call(session)
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(session.post.call_count, 3)

    async def test_shared_deadline_cancels_a_hanging_request(self):
        session = self.session([200])
        async def wait_forever():
            await asyncio.Event().wait()
        context = MagicMock()
        context.__aenter__ = AsyncMock(side_effect=wait_forever)
        context.__aexit__ = AsyncMock(return_value=False)
        session.post.side_effect = None
        session.post.return_value = context
        timeout = asyncio.timeout
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                patch("horsie.reality_check.asyncio.timeout", side_effect=lambda _: timeout(0.01)), \
                self.assertRaises(asyncio.TimeoutError):
            await request_gemini(session, "gemini-3.8-flash", {})
        self.assertEqual(session.post.call_count, 1)


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    def response(self, data=b"\x89PNG\r\n\x1a\nimage", status=200, headers=None, length=None):
        async def chunks(_):
            yield data
        return NS(status=status, headers=headers or {}, content_length=length,
                  content=NS(iter_chunked=chunks))

    def session(self, *responses):
        session = MagicMock()
        contexts = []
        for response in responses:
            context = MagicMock()
            context.__aenter__ = AsyncMock(return_value=response)
            context.__aexit__ = AsyncMock(return_value=False)
            contexts.append(context)
        session.get.side_effect = contexts
        return session

    async def test_image_signatures_and_no_key_forwarded_to_image_host(self):
        for data, mime in [(b"\x89PNG\r\n\x1a\nimage", "image/png"),
                           (b"\xff\xd8\xffimage", "image/jpeg"),
                           (b"RIFF1234WEBPimage", "image/webp"), (b"GIF89aimage", "image/gif")]:
            session = self.session(self.response(data))
            self.assertEqual(await download_image(session, "https://example.com/a.png"), (mime, data))
            self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
            self.assertNotIn("headers", session.get.call_args.kwargs)

    async def test_private_links_and_redirects_are_rejected_before_fetch(self):
        for url in ["http://example.com/a.png", "https://127.0.0.1/a.png",
                    "https://169.254.169.254/a.png", "https://[::1]/a.png",
                    "https://user:password@example.com/a.png", "https://example.com:8443/a.png"]:
            with self.subTest(url=url), self.assertRaises(CheckError):
                validate_image_url(url)
        session = self.session(self.response(status=302, headers={"Location": "https://127.0.0.1/a.png"}))
        with self.assertRaises(CheckError):
            await download_image(session, "https://example.com/a.png")
        session.get.assert_called_once()

    async def test_dns_private_addresses_are_rejected(self):
        resolver = PublicImageResolver()
        try:
            with patch("aiohttp.resolver.ThreadedResolver.resolve", AsyncMock(return_value=[{"host": "10.0.0.1"}])), \
                    self.assertRaises(CheckError):
                await resolver.resolve("internal.example", 443)
        finally:
            await resolver.close()

    async def test_external_redirect_and_size_and_invalid_content(self):
        session = self.session(self.response(status=302, headers={"Location": "/new.png"}), self.response())
        self.assertEqual((await download_image(session, "https://example.com/a.png"))[0], "image/png")
        self.assertEqual(session.get.call_args.args[0], "https://example.com/new.png")
        for response in [self.response(status=404), self.response(b"<html>"),
                         self.response(length=9 * 1024 * 1024), self.response(b"x" * (8 * 1024 * 1024 + 1))]:
            with self.assertRaises(CheckError):
                await download_image(self.session(response), "https://example.com/a.png")
