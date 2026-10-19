import asyncio
import base64
import io
import json
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import aiohttp
from PIL import Image

from horsie.reality_check import GIF_CAUTION, CheckError, QuotaError, RealityCheck, assess, download_image, image_urls, validate_image_url, PublicImageResolver, groq_error, request_groq, gif_parts, find_message_images, resolve_image_page


def gif_fixture(count=10, durations=100):
    frames = [Image.new("RGB", (20, 20), (i * 21 % 256, 255 - i * 19 % 256, i * 13 % 256)) for i in range(count)]
    output = io.BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0)
    return output.getvalue()


def webp_fixture(count=247):
    frames = [Image.new("RGB", (20, 20), (i % 256, 255 - i % 256, 0)) for i in range(count)]
    output = io.BytesIO()
    frames[0].save(output, format="WEBP", save_all=True, append_images=frames[1:], duration=40, lossless=True)
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
        self.env = patch.dict(os.environ, {"GROQ_API_KEY": "test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def test_mention_variants_find_image_past_intervening_chat(self):
        for text in ["<@42> is this real?", "is it real <@!42>", "<@42> real or AI?",
                     "<@42> is that AI?", "<@42> if its real", "<@42>", "<@!42>", "<@42> hello"]:
            with self.subTest(text=text):
                cog = RealityCheck(NS(user=NS(id=42)))
                request, image = message(text), photo()
                history(request.channel, [message("hello", id=99), image, photo(id=89)])
                with patch("horsie.reality_check.assess", AsyncMock(return_value="assessment")) as check:
                    await cog.on_message(request)
                self.assertEqual(check.await_args.args[1], [image.attachments[0].url])
                self.assertIn(image.jump_url, request.reply.await_args.args[0])
                self.assertFalse(request.reply.await_args.kwargs["allowed_mentions"].everyone)
                request.channel.history.assert_called_once_with(limit=None, before=request, oldest_first=False)

    async def test_ignores_unmentioned_other_bots_webhooks_and_dms(self):
        cases = [message("is this real?"), message("<@99> is this real?")]
        for field, value in [("author", NS(id=7, bot=True)), ("webhook_id", 8), ("guild", None)]:
            msg = message("<@42> is this real?")
            setattr(msg, field, value)
            cases.append(msg)
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            for msg in cases:
                await self.cog.on_message(msg)
                msg.reply.assert_not_awaited()
            check.assert_not_awaited()

    async def test_reply_does_not_override_the_asking_users_own_image(self):
        request = message("<@42> is this real?")
        request.reference = NS(channel_id=999, message_id=80)
        own, other = photo(id=90), photo(id=80)
        other.author.id = 8
        history(request.channel, [other, own])
        selected, _ = await self.cog.target(request)
        self.assertIs(selected, own)
        request.channel.fetch_message.assert_not_awaited()

    async def test_attached_request_image_takes_priority(self):
        request = photo()
        self.assertIs((await self.cog.target(request))[0], request)

    async def test_long_reply_preserves_full_explanation_and_source(self):
        request = message("<@42>")
        image = photo()
        history(request.channel, [image])
        for answer in ("**Inconclusive**\n" + "A complete sentence. " * 200,
                       "**Inconclusive**\n" + "x" * 4000):
            with self.subTest(answer=answer[:40]):
                cog = RealityCheck(NS(user=NS(id=42)))
                request.reply.reset_mock()
                with patch("horsie.reality_check.assess", AsyncMock(return_value=answer)):
                    await cog.on_message(request)
                parts = [call.args[0] for call in request.reply.await_args_list]
                self.assertGreater(len(parts), 1)
                self.assertTrue(all(len(part) <= 2000 for part in parts))
                self.assertEqual("".join(parts), f"Checking: {image.jump_url}\n" + answer)
                for call in request.reply.await_args_list:
                    self.assertFalse(call.kwargs["allowed_mentions"].everyone)

    async def test_missing_image_and_missing_key_never_call_api(self):
        request = message("<@42> is this real?")
        history(request.channel, [message("just text")])
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            await self.cog.on_message(request)
            self.assertIn("couldn't find", request.reply.await_args.args[0])
            self.assertFalse(self.cog.active_checks)
            with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
                request.author.id = 8
                await self.cog.on_message(request)
            self.assertIn("GROQ_API_KEY", request.reply.await_args.args[0])
            check.assert_not_awaited()

    async def test_cooldown_and_failure_release_busy_channel(self):
        request = message("<@42> is this real?")
        history(request.channel, [photo()])
        with patch("horsie.reality_check.assess", AsyncMock(side_effect=asyncio.TimeoutError)) as check:
            await self.cog.on_message(request)
            await self.cog.on_message(request)
            check.assert_awaited_once()
        self.assertFalse(self.cog.active_checks)
        self.assertIn("couldn't finish", request.reply.await_args_list[0].args[0])
        self.assertIn("Please wait about", request.reply.await_args.args[0])

    async def test_another_users_image_is_never_selected(self):
        request = message("<@42> is this real?")
        other = photo()
        other.author.id = 8
        history(request.channel, [other])
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            await self.cog.on_message(request)
            check.assert_not_awaited()
        self.assertIn("your last five messages", request.reply.await_args.args[0])
        self.assertFalse(self.cog.active_checks)

    async def test_five_user_messages_are_counted_not_five_channel_messages(self):
        request = message("<@42> is this real?")
        chatter = [message(id=i) for i in range(200, 260)]
        for other in chatter:
            other.author.id = 8
        own = photo()
        history(request.channel, chatter + [message() for _ in range(4)] + [own])
        self.assertIs((await self.cog.target(request))[0], own)

    async def test_sixth_user_message_is_outside_search_window(self):
        request = message("<@42> is this real?")
        history(request.channel, [message() for _ in range(5)] + [photo()])
        with self.assertRaisesRegex(CheckError, "last five"):
            await self.cog.target(request)

    async def test_each_asking_user_gets_their_own_latest_image(self):
        first, second = message("<@42> is this real?"), message("<@42> is this real?", id=101)
        second.author.id = 8
        first_image, second_image = photo(id=90), photo(id=80)
        second_image.author.id = 8
        history(first.channel, [first_image, second_image])
        history(second.channel, [first, first_image, second_image])
        with patch("horsie.reality_check.assess", AsyncMock(return_value="assessment")):
            await self.cog.on_message(first)
            await self.cog.on_message(second)
        self.assertIn(first_image.jump_url, first.reply.await_args.args[0])
        self.assertIn(second_image.jump_url, second.reply.await_args.args[0])

    async def test_link_without_discord_preview_is_selected_for_its_author(self):
        request = message("<@42> is this real?")
        linked = message("https://tenor.com/view/cat-gif-123", id=90)
        history(request.channel, [linked, photo(id=80)])
        with patch("horsie.reality_check.resolve_image_page", AsyncMock(return_value=["https://media.tenor.com/id/tenor.gif"])):
            selected, images = await self.cog.target(request)
        self.assertIs(selected, linked)
        self.assertEqual(images, ["https://media.tenor.com/id/tenor.gif"])

    async def test_newest_of_the_users_image_messages_wins(self):
        request = message("<@42> is this real?")
        recent = photo(id=95)
        history(request.channel, [recent, photo(id=90)])
        self.assertIs((await self.cog.target(request))[0], recent)

    async def test_klipy_gif_uses_animated_webp_without_opening_blocked_page(self):
        request = message("<@42> is this real?")
        url = "https://static.klipy.com/ii/example/gorilla.webp"
        embed = discord.Embed.from_dict({
            "type": "gifv", "thumbnail": {"url": url},
            "video": {"url": "https://static.klipy.com/ii/example/gorilla.mp4"},
        })
        linked = message("https://klipy.com/gifs/gorilla-become-a-gorilla", embeds=[embed], id=90)
        history(request.channel, [message("intervening chat"), linked])
        with patch("horsie.reality_check.resolve_image_page", AsyncMock()) as resolve:
            selected, images = await self.cog.target(request)
        self.assertIs(selected, linked)
        self.assertEqual(images, [url])
        resolve.assert_not_awaited()

    async def test_full_queue_does_not_start_another_request(self):
        request = message("<@42>")
        self.cog.active_checks.update({1, 2, 3})
        with patch("horsie.reality_check.assess", AsyncMock()) as check:
            await self.cog.on_message(request)
            check.assert_not_awaited()
        self.assertIn("queue is full", request.reply.await_args.args[0])
        self.assertEqual(self.cog.active_checks, {1, 2, 3})

    async def test_same_channel_checks_wait_and_keep_each_users_media(self):
        first, second = photo(id=100), photo(id=101)
        first.content = second.content = "<@42>"
        second.author.id = 8
        second.channel = first.channel
        second.attachments[0].url = "https://example.com/second.png"
        started, release = asyncio.Event(), asyncio.Event()

        async def slow_assess(text, images):
            if images == [first.attachments[0].url]:
                started.set()
                await release.wait()
            return "assessment for " + images[0]

        with patch("horsie.reality_check.assess", AsyncMock(side_effect=slow_assess)) as check:
            first_task = asyncio.create_task(self.cog.on_message(first))
            second_task = None
            try:
                await asyncio.wait_for(started.wait(), timeout=2)
                acknowledged = asyncio.Event()
                async def reply(*args, **kwargs):
                    acknowledged.set()
                second.reply.side_effect = reply
                second_task = asyncio.create_task(self.cog.on_message(second))
                await asyncio.wait_for(acknowledged.wait(), timeout=2)
                self.assertIn("check yours next", second.reply.await_args.args[0])
                self.assertEqual(check.await_count, 1)
                release.set()
                await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=2)
            finally:
                release.set()
                for task in (first_task, second_task):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(*(task for task in (first_task, second_task) if task is not None), return_exceptions=True)
        self.assertEqual(check.await_count, 2)
        self.assertIn(first.attachments[0].url, first.reply.await_args.args[0])
        self.assertIn(second.attachments[0].url, second.reply.await_args.args[0])
        self.assertFalse(self.cog.active_checks)

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
    async def call_api(self, status=200, body=None, model=None, mime="image/png", data=b"image bytes", images=None, responses=None):
        response = MagicMock(status=status)
        response.json = AsyncMock(return_value=body)
        if responses is not None:
            response.json.side_effect = responses
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}), \
                patch("horsie.reality_check.aiohttp.ClientSession", factory), \
                patch("horsie.reality_check.aiohttp.TCPConnector"), \
                patch("horsie.reality_check.asyncio.sleep", AsyncMock()), \
                patch("horsie.reality_check.download_image", AsyncMock(return_value=(mime, data))):
            if model is None:
                os.environ.pop("GROQ_REALITY_CHECK_MODEL", None)
            else:
                os.environ["GROQ_REALITY_CHECK_MODEL"] = model
            answer = await assess("image", images or ["https://example.com/image.png"])
        expected_model = model or "qwen/qwen3.8-27b"
        self.assertEqual(session.post.call_args.args[0], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(session.post.call_args_list[0].kwargs["json"]["model"], expected_model)
        self.assertEqual(session.post.call_args.kwargs["headers"], {"Authorization": "Bearer test-key"})
        self.assertFalse(session.post.call_args.kwargs["allow_redirects"])
        self.last_requests = session.post.call_args_list
        return answer, session.post.call_args_list[0].kwargs["json"]

    def assessment_body(self, verdict="Inconclusive", needs_review=False, reasons="The sampled image is unclear."):
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "observations": ["An animal is visible."], "needs_review": needs_review,
            "verdict": verdict, "reasons": reasons,
        })}}]}

    async def test_review_uses_different_frames_and_can_resolve_uncertainty(self):
        first = self.assessment_body()
        review = self.assessment_body("Likely authentic", reasons="The clearer frames show consistent details.")
        answer, _ = await self.call_api(responses=[first, review], mime="image/gif", data=gif_fixture())
        self.assertIn("Likely authentic", answer)
        self.assertEqual(len(self.last_requests), 2)
        contents = [call.kwargs["json"]["messages"][1]["content"] for call in self.last_requests]
        frames = [{part["image_url"]["url"] for part in content if part["type"] == "image_url"} for content in contents]
        self.assertFalse(frames[0] & frames[1])
        self.assertTrue(all(len(group) <= 3 for group in frames))

    async def test_decisive_first_result_does_not_pay_for_review(self):
        await self.call_api(body=self.assessment_body("Likely authentic"))
        self.assertEqual(len(self.last_requests), 1)

    async def test_conflicting_checks_and_unresolved_review_abstain(self):
        for first, review in ((self.assessment_body("Likely AI-generated", True), self.assessment_body("Likely authentic")),
                              (self.assessment_body(), self.assessment_body("Likely AI-generated", True))):
            answer, _ = await self.call_api(responses=[first, review])
            self.assertTrue(answer.startswith("**Inconclusive**"))

    async def test_failed_review_preserves_first_answer_and_carries_quota_pause(self):
        for failure in (CheckError("unavailable"), asyncio.TimeoutError(), QuotaError(42)):
            answer, _ = await self.call_api(responses=[self.assessment_body(), failure, failure, failure])
            self.assertIn("The sampled image is unclear.", answer)
            self.assertEqual(getattr(answer, "quota_error", None), failure if isinstance(failure, QuotaError) else None)

    async def test_invalid_observations_are_rejected(self):
        for observations in ([], [""], [12], ["one"] * 4, "not a list"):
            body = self.assessment_body()
            content = json.loads(body["choices"][0]["message"]["content"])
            content["observations"] = observations
            body["choices"][0]["message"]["content"] = json.dumps(content)
            with self.assertRaises(CheckError):
                await self.call_api(body=body)

    async def test_request_and_visible_uncertainty(self):
        body = {"choices": [{"finish_reason": "stop", "message": {
            "content": '{"observations":["Visible details are ambiguous."],"needs_review":false,"verdict":"Inconclusive","reasons":"No reliable clues."}',
        }}]}
        answer, payload = await self.call_api(body=body)
        self.assertEqual(answer, "**Inconclusive**\nNo reliable clues.")
        self.assertIn("Inconclusive", answer)
        inline = payload["messages"][1]["content"][1]["image_url"]["url"]
        self.assertTrue(inline.startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(inline.split(",", 1)[1]), b"image bytes")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(payload["max_completion_tokens"], 1500)

    async def test_complete_explanation_is_not_sliced_at_1000_characters(self):
        reasons = "Visible details are ambiguous. " * 45 + "This is the final sentence."
        body = {"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"observations": ["Visible details are ambiguous."], "needs_review": False, "verdict": "Inconclusive", "reasons": reasons}),
        }}]}
        answer, _ = await self.call_api(body=body)
        self.assertEqual(answer, "**Inconclusive**\n" + reasons)

    async def test_api_failures_and_bad_or_incomplete_responses(self):
        for status, body in [(429, {}), (401, {}), (500, {}), (200, {}),
                             (200, {"choices": []}),
                             (200, {"choices": [{"finish_reason": "length"}]}),
                             (200, {"choices": [{"finish_reason": "content_filter"}]}),
                             (200, {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]})]:
            with self.subTest(status=status, body=body), self.assertRaises(CheckError):
                await self.call_api(status, body)

    async def test_gif_submits_sampled_pngs_and_discloses_sampling(self):
        body = {"choices": [{"finish_reason": "stop", "message": {
            "content": '{"observations":["Visible details are ambiguous."],"needs_review":false,"verdict":"Inconclusive","reasons":"Only sampled frames are available."}',
        }}]}
        answer, payload = await self.call_api(body=body, mime="image/gif", data=gif_fixture())
        self.assertIn(GIF_CAUTION, answer)
        parts = payload["messages"][1]["content"]
        images = [part["image_url"]["url"] for part in parts if part.get("type") == "image_url"]
        self.assertEqual(len(images), 3)
        self.assertTrue(all(part.startswith("data:image/png;base64,") for part in images))
        self.assertIn("frame 10 of 10", parts[-2]["text"])

    async def test_animated_webp_submits_first_middle_last_frames(self):
        body = {"choices": [{"finish_reason": "stop", "message": {
            "content": '{"observations":["Visible details are ambiguous."],"needs_review":false,"verdict":"Inconclusive","reasons":"Sampled frames only."}',
        }}]}
        answer, payload = await self.call_api(body=body, mime="image/webp", data=webp_fixture())
        self.assertIn("Animated WebP assessment uses sampled frames", answer)
        parts = payload["messages"][1]["content"]
        images = [p["image_url"]["url"] for p in parts if p.get("type") == "image_url"]
        self.assertEqual(len(images), 3)
        self.assertTrue(all(url.startswith("data:image/png;base64,") for url in images))
        labels = [p["text"] for p in parts if p.get("text", "").startswith("animated WebP")]
        self.assertEqual([label.split(" of ")[0] for label in labels],
                         ["animated WebP sampled frame 1", "animated WebP sampled frame 124", "animated WebP sampled frame 247"])

    async def test_static_webp_remains_a_single_image(self):
        body = {"choices": [{"finish_reason": "stop", "message": {
            "content": '{"observations":["Visible details are ambiguous."],"needs_review":false,"verdict":"Inconclusive","reasons":"No reliable clues."}',
        }}]}
        answer, payload = await self.call_api(body=body, mime="image/webp", data=webp_fixture(1))
        parts = payload["messages"][1]["content"]
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/webp;base64,"))
        self.assertNotIn("sampled frames", answer)

    async def test_combined_size_limit_prevents_api_request(self):
        with patch.dict(os.environ, {"GROQ_REALITY_CHECK_MODEL": "qwen/qwen3.8-27b"}), \
                patch("horsie.reality_check.MAX_TOTAL_IMAGE_BYTES", 2), \
                patch("horsie.reality_check.download_image", AsyncMock(return_value=("image/png", b"large"))), \
                self.assertRaisesRegex(CheckError, "too large together"):
            await assess("image", ["https://example.com/image.png"])

    async def test_multiple_gifs_share_the_three_image_budget(self):
        body = {"choices": [{"finish_reason": "stop", "message": {
            "content": '{"observations":["Visible details are ambiguous."],"needs_review":false,"verdict":"Inconclusive","reasons":"Sampled frames only."}',
        }}]}
        for count in (2, 3):
            with self.subTest(sources=count):
                _, payload = await self.call_api(body=body, mime="image/gif", data=gif_fixture(),
                    images=[f"https://example.com/{i}.gif" for i in range(count)])
                parts = payload["messages"][1]["content"]
                self.assertEqual(sum(part.get("type") == "image_url" for part in parts), 3)

    async def test_groq_model_setting_ignores_old_provider_override(self):
        body = {"choices": [{"finish_reason": "stop", "message": {
            "content": '{"observations":["Visible details are ambiguous."],"needs_review":false,"verdict":"Inconclusive","reasons":"No reliable clues."}',
        }}]}
        with patch.dict(os.environ, {"REALITY_CHECK_MODEL": "gemini-3.8-flash"}):
            _, payload = await self.call_api(body=body)
        self.assertEqual(payload["model"], "qwen/qwen3.8-27b")

    async def test_old_model_override_has_clear_error(self):
        with patch.dict(os.environ, {"GROQ_REALITY_CHECK_MODEL": "gpt-4.1-mini"}), \
                self.assertRaisesRegex(CheckError, "GROQ_REALITY_CHECK_MODEL"):
            await assess("image", ["https://example.com/image.png"])

    def test_actionable_errors_do_not_expose_google_error_body(self):
        for status, body, expected in [
            (404, {"error": {"message": "Model is no longer available to new users"}}, "GROQ_REALITY_CHECK_MODEL"),
            (400, {"error": {"message": "API key not valid: secret-key"}}, "GROQ_API_KEY"),
            (403, {}, "restrictions"), (429, {}, "usage limit"),
            (400, {}, "request settings"), (503, None, "temporarily unavailable"),
        ]:
            with self.subTest(status=status):
                result = str(groq_error(status, body))
                self.assertIn(expected, result)
                self.assertNotIn("secret-key", result)


class GifTests(unittest.TestCase):
    def test_playback_time_sampling_handles_a_long_held_frame(self):
        parts = gif_parts(gif_fixture(10, durations=[900] + [10] * 9))
        labels = [part["text"] for part in parts if "text" in part]
        self.assertEqual(len(labels), 2)  # Mid-playback is still the first frame.
        self.assertIn("frame 1 of 10", labels[0])
        self.assertIn("frame 10 of 10", labels[1])
        review = gif_parts(gif_fixture(10, durations=[900] + [10] * 9), alternate=True)
        self.assertEqual(len(review), 6)
        self.assertTrue(all("frame 1 of 10" not in part["text"] and "frame 10 of 10" not in part["text"]
                            for part in review if "text" in part))

    def test_zero_duration_gifs_use_a_safe_fallback(self):
        parts = gif_parts(gif_fixture(10, durations=0))
        self.assertEqual(len(parts), 6)
        self.assertIn("1000 ms", parts[0]["text"])

    def test_sampled_frames_preserve_decoded_pixels_without_lossy_compression(self):
        for media_format, data in (("GIF", gif_fixture(10)), ("WEBP", webp_fixture(10))):
            with self.subTest(media_format=media_format), Image.open(io.BytesIO(data)) as source:
                parts = gif_parts(data, media_format=media_format)
                for index, part in zip((0, 4, 9), parts[1::2]):
                    source.seek(index)
                    rgba = source.convert("RGBA")
                    expected = Image.new("RGB", rgba.size, "white")
                    expected.paste(rgba, mask=rgba.getchannel("A"))
                    encoded = part["image_url"]["url"].split(",", 1)[1]
                    with Image.open(io.BytesIO(base64.b64decode(encoded))) as actual:
                        self.assertEqual(actual.format, "PNG")
                        self.assertEqual(actual.tobytes(), expected.tobytes())

    def test_samples_first_middle_and_last_frames(self):
        parts = gif_parts(gif_fixture())
        labels = [part["text"] for part in parts if "text" in part]
        self.assertEqual([label.split(" of ")[0] for label in labels],
                         ["GIF sampled frame 1", "GIF sampled frame 5", "GIF sampled frame 10"])
        first = Image.open(io.BytesIO(base64.b64decode(parts[1]["image_url"]["url"].split(",", 1)[1])))
        last = Image.open(io.BytesIO(base64.b64decode(parts[-1]["image_url"]["url"].split(",", 1)[1])))
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

    def test_webp_animation_limits_are_enforced(self):
        with self.assertRaisesRegex(CheckError, "too long"):
            gif_parts(webp_fixture(401), media_format="WEBP")


class QuotaAndCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_quota_returns_and_caches_answer_but_pauses_new_checks(self):
        from horsie.reality_check import AssessmentReply
        cog = RealityCheck(NS(user=NS(id=42)))
        answer = AssessmentReply("**Inconclusive**\nSome details are unclear.", QuotaError(42))
        with patch("horsie.reality_check.assess", AsyncMock(return_value=answer)) as check:
            self.assertEqual(await cog.assessment(message(), ["https://example.com/a.png"]), answer)
            self.assertIn(answer, await cog.assessment(message(), ["https://example.com/a.png"]))
            with self.assertRaises(QuotaError):
                await cog.assessment(message(), ["https://example.com/b.png"])
            check.assert_awaited_once()

    def test_retry_delay_and_daily_quota_are_distinguished(self):
        body = {"error": {"message": "Rate limit reached on tokens per minute (TPM). Please try again in 23.4s."}}
        error = groq_error(429, body)
        self.assertIsInstance(error, QuotaError)
        self.assertEqual(error.seconds, 24)
        self.assertFalse(error.daily)
        self.assertIn("24 seconds", str(error))
        body["error"]["message"] = "Rate limit reached on tokens per day (TPD). Please try again in 1h2m3.4s."
        self.assertTrue(groq_error(429, body).daily)
        self.assertEqual(groq_error(429, body).seconds, 3724)
        self.assertIn("daily quota reset", str(groq_error(429, body)))
        self.assertEqual(groq_error(429, {}, "45").seconds, 45)
        self.assertEqual(groq_error(429, {}).seconds, 60)

    async def test_repeat_check_uses_cached_answer_but_different_image_does_not(self):
        cog = RealityCheck(NS(user=NS(id=42)))
        request = message()
        with patch("horsie.reality_check.assess", AsyncMock(side_effect=["first assessment", "second assessment"])) as check:
            self.assertEqual(await cog.assessment(request, ["https://example.com/one.png"]), "first assessment")
            cached = await cog.assessment(request, ["https://example.com/one.png"])
            self.assertIn("cached", cached)
            self.assertIn("first assessment", cached)
            self.assertEqual(await cog.assessment(request, ["https://example.com/two.png"]), "second assessment")
        self.assertEqual(check.await_count, 2)

    async def test_global_quota_backoff_stops_other_users_calling_api(self):
        cog = RealityCheck(NS(user=NS(id=42)))
        first, second = message(), message()
        second.author.id = 8
        with patch("horsie.reality_check.assess", AsyncMock(side_effect=QuotaError(42))) as check:
            with self.assertRaises(QuotaError):
                await cog.assessment(first, ["https://example.com/one.png"])
            with self.assertRaises(QuotaError) as caught:
                await cog.assessment(second, ["https://example.com/two.png"])
        self.assertTrue(0 < caught.exception.seconds <= 42)
        check.assert_awaited_once()
        self.assertFalse(cog.assessments)

    async def test_cached_assessment_stays_available_during_backoff(self):
        cog = RealityCheck(NS(user=NS(id=42)))
        with patch("horsie.reality_check.assess", AsyncMock(return_value="assessment")) as check:
            await cog.assessment(message(), ["https://example.com/one.png"])
            cog.blocked_until = asyncio.get_running_loop().time() + 60
            self.assertIn("cached", await cog.assessment(message(), ["https://example.com/one.png"]))
        check.assert_awaited_once()

    async def test_expired_results_are_refreshed_and_simultaneous_checks_share_result(self):
        cog = RealityCheck(NS(user=NS(id=42)))
        images = ["https://example.com/one.png"]
        with patch("horsie.reality_check.assess", AsyncMock(return_value="assessment")) as check:
            results = await asyncio.gather(cog.assessment(message(), images), cog.assessment(message(), images))
            self.assertEqual(check.await_count, 1)
            self.assertTrue(any("cached" in result for result in results))
            key = next(iter(cog.assessments))
            cog.assessments[key] = (asyncio.get_running_loop().time() - 1801, "old")
            await cog.assessment(message(), images)
            self.assertEqual(check.await_count, 2)


class RetryTests(unittest.IsolatedAsyncioTestCase):
    def session(self, outcomes):
        session = MagicMock()
        contexts = []
        for outcome in outcomes:
            context = MagicMock()
            if isinstance(outcome, Exception):
                context.__aenter__ = AsyncMock(side_effect=outcome)
            else:
                status, body = outcome if isinstance(outcome, tuple) else (outcome, {"result": "ok"})
                response = NS(status=status, json=AsyncMock(return_value=body))
                context.__aenter__ = AsyncMock(return_value=response)
            context.__aexit__ = AsyncMock(return_value=False)
            contexts.append(context)
        session.post.side_effect = contexts
        return session

    async def call(self, session):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}), \
                patch("horsie.reality_check.asyncio.sleep", AsyncMock()) as sleep:
            result = await request_groq(session, "qwen/qwen3.8-27b", {"images": "same payload"})
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

    async def test_structured_generation_failure_is_retried_but_bounded(self):
        failure = (400, {"error": {"code": "json_validate_failed"}})
        session = self.session([failure, 200])
        result, _ = await self.call(session)
        self.assertEqual(result, {"result": "ok"})
        self.assertEqual(session.post.call_count, 2)
        session = self.session([failure, failure, failure])
        with self.assertRaisesRegex(CheckError, "structured image assessment after three attempts"):
            await self.call(session)
        self.assertEqual(session.post.call_count, 3)

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
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}), \
                patch("horsie.reality_check.asyncio.timeout", side_effect=lambda _: timeout(0.01)), \
                self.assertRaises(asyncio.TimeoutError):
            await request_groq(session, "qwen/qwen3.8-27b", {})
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


class LinkResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_imgur_rate_limit_is_explicit_and_not_retried_as_more_extensions(self):
        session = self.session(status=429, content_type="application/json")
        with self.assertRaisesRegex(CheckError, "Imgur is rate-limiting"):
            await resolve_image_page(session, "https://imgur.com/abc123")
        session.get.assert_called_once()
        with patch("horsie.reality_check.resolve_image_page", AsyncMock(side_effect=CheckError("Imgur is rate-limiting"))):
            with self.assertRaisesRegex(CheckError, "Imgur is rate-limiting"):
                await find_message_images(message("https://imgur.com/abc123"))

    async def test_imgur_direct_and_gifv_links_override_static_previews(self):
        preview = discord.Embed(type="image").set_image(url="https://i.imgur.com/abc123h.jpg")
        for link, expected in (("https://i.imgur.com/abc123.gifv", "https://i.imgur.com/abc123.gif"),
                               ("http://imgur.com/abc123.png", "https://i.imgur.com/abc123.png"),
                               ("https://i.imgur.com/abc123.mp4", "https://i.imgur.com/abc123.gif")):
            self.assertEqual(image_urls(message(link, embeds=[preview])), [expected])
        self.assertEqual(image_urls(message("https://imgur.com.evil.test/abc123.gifv")), [])

    async def test_imgur_share_link_resolves_without_javascript(self):
        session = self.session(content_type="image/gif")
        self.assertEqual(await resolve_image_page(session, "https://imgur.com/abc123"), ["https://i.imgur.com/abc123.gif"])
        self.assertEqual(session.get.call_args.args[0], "https://i.imgur.com/abc123.gif")
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    async def test_reported_imgur_link_uses_identified_media_session(self):
        from horsie.reality_check import MEDIA_HEADERS
        session = self.session(content_type="image/jpeg")
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch("horsie.reality_check.aiohttp.ClientSession", factory), patch("horsie.reality_check.aiohttp.TCPConnector"):
            images = await find_message_images(message("https://imgur.com/EEOQF3o"))
        self.assertEqual(images, ["https://i.imgur.com/EEOQF3o.gif"])
        self.assertEqual(factory.call_args.kwargs["headers"], MEDIA_HEADERS)

    async def test_imgur_album_uses_actual_cover_metadata_not_album_id(self):
        session = self.session(b'<meta property="og:image" content="https://i.imgur.com/actual.png">')
        self.assertEqual(await resolve_image_page(session, "https://imgur.com/a/album123"), ["https://i.imgur.com/actual.png"])
        self.assertEqual(session.get.call_args.args[0], "https://imgur.com/a/album123")

    async def test_imgur_animated_metadata_wins_over_static_thumbnail(self):
        session = self.session(b'<meta property="og:image" content="https://i.imgur.com/still.jpg"><meta property="og:video" content="https://i.imgur.com/animation.mp4">')
        self.assertEqual(await resolve_image_page(session, "https://imgur.com/a/album123"), ["https://i.imgur.com/animation.gif"])

    async def test_unreadable_imgur_link_does_not_silently_check_an_old_image(self):
        request = message("<@42> https://imgur.com/a/unreadable")
        history(request.channel, [photo()])
        with patch("horsie.reality_check.find_message_images", AsyncMock(return_value=[])):
            with self.assertRaisesRegex(CheckError, "Imgur"):
                await RealityCheck(NS(user=NS(id=42))).target(request)

    def session(self, body=b"", content_type="text/html", status=200, headers=None):
        async def chunks(_):
            yield body
        response = NS(status=status, content_type=content_type, headers=headers or {},
                      content=NS(iter_chunked=chunks))
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.get.return_value = context
        return session

    async def test_image_page_resolves_encoded_relative_and_duplicate_metadata(self):
        session = self.session(b'''<meta content="/cat.gif?a=1&amp;b=2" property="og:image">
            <meta name="twitter:image" content="/cat.gif?a=1&amp;b=2">''')
        result = await resolve_image_page(session, "https://example.com/view/cat")
        self.assertEqual(result, ["https://example.com/cat.gif?a=1&b=2"])
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    async def test_extensionless_direct_media_is_recognized_by_content_type(self):
        session = self.session(content_type="image/gif")
        result = await resolve_image_page(session, "https://example.com/media?id=123")
        self.assertEqual(result, ["https://example.com/media?id=123"])

    async def test_gif_page_prefers_animation_over_its_static_previews(self):
        session = self.session(b'''<meta property="og:image" content="/cat.webp">
            <meta property="og:image:secure_url" content="/cat_s.gif">
            <meta name="twitter:image" content="/cat.gif">''')
        self.assertEqual(await resolve_image_page(session, "https://example.com/view"), ["https://example.com/cat.gif"])

    async def test_private_metadata_and_private_redirect_are_rejected(self):
        session = self.session(b'<meta property="og:image" content="https://127.0.0.1/private.png">')
        self.assertEqual(await resolve_image_page(session, "https://example.com/view"), [])
        session = self.session(status=302, headers={"Location": "https://169.254.169.254/a"})
        with self.assertRaises(CheckError):
            await resolve_image_page(session, "https://example.com/view")
        session.get.assert_called_once()

    async def test_page_read_limit_and_nonimage_pages(self):
        session = self.session(b"x" * (256 * 1024) + b'<meta property="og:image" content="/outside.png">')
        self.assertEqual(await resolve_image_page(session, "https://example.com/view"), [])
        self.assertEqual(await resolve_image_page(self.session(content_type="application/pdf"), "https://example.com/view"), [])

    async def test_failed_link_does_not_hide_later_image_link(self):
        msg = message("https://example.com/not-an-image https://example.com/gallery")
        with patch("horsie.reality_check.resolve_image_page", AsyncMock(side_effect=[[], ["https://example.com/a.png"]])) as resolve:
            self.assertEqual(await find_message_images(msg), ["https://example.com/a.png"])
        self.assertEqual(resolve.await_count, 2)

    async def test_markdown_links_and_extensionless_discord_previews(self):
        self.assertEqual(image_urls(message("[image](https://example.com/cat.gif)")), ["https://example.com/cat.gif"])
        embed = discord.Embed(type="image").set_image(url="https://example.com/media?id=1")
        self.assertEqual(await find_message_images(message(embeds=[embed])), ["https://example.com/media?id=1"])
