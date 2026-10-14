import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import horse_articles as articles


NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


def story(title, days_ago, suffix, body=None):
    return {
        "title": title,
        "url": f"https://www.horseandhound.co.uk/features/{suffix}",
        "published": NOW - timedelta(days=days_ago),
        "body": body or ("The pony played in a sunny field with its friends. " * 6),
        "description": "A cheerful pony story.",
    }


class ArticleFilterTests(unittest.TestCase):
    def test_latest_unseen_then_older_without_repeating(self):
        newest = story("A cute pony makes friends", 1, "one")
        older = story("A playful foal explores a field", 30, "two")
        self.assertEqual(articles.choose_article([older, newest], NOW)["url"], newest["url"])
        self.assertEqual(articles.choose_article([older, newest], NOW, [newest["url"]])["url"], older["url"])
        self.assertIsNone(articles.choose_article([older, newest], NOW, [newest["url"], older["url"]]))

    def test_distressing_context_and_stale_stories_are_rejected(self):
        bad = story("Cute pony finds a friend", 0, "sad", body="The horse died later. " * 30)
        old = story("Adorable foal learns to play", 366, "old")
        unknown = story("Horse meeting", 0, "plain")
        self.assertIsNone(articles.choose_article([bad, old, unknown], NOW))

    def test_missing_full_text_and_outside_links_are_rejected(self):
        xml = f"""<rss><channel>
            <item><title>Adorable foal</title><link>https://www.horseandhound.co.uk/features/empty</link><pubDate>{format_datetime(NOW)}</pubDate><description>Cute!</description></item>
            <item><title>Adorable foal</title><link>https://evil.example/story</link><pubDate>{format_datetime(NOW)}</pubDate><description>Cute!</description><body>{'hello ' * 100}</body></item>
        </channel></rss>"""
        self.assertEqual(articles.parse_articles(xml.encode()), [])

    def test_full_feed_content_is_screened(self):
        body = "The pony played happily. " * 12 + " The horse was injured."
        xml = f"""<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
            <item><title>A sweet foal</title><link>https://www.horseandhound.co.uk/features/foal</link>
            <pubDate>{format_datetime(NOW)}</pubDate><dc:content><![CDATA[<article><p>{body}</p></article>]]></dc:content></item>
        </channel></rss>"""
        parsed = articles.parse_articles(xml.encode())
        self.assertEqual(len(parsed), 1)
        self.assertIsNone(articles.choose_article(parsed, NOW))

    def test_horse_nation_full_text_source_and_light_series(self):
        body = "Enjoy these photos of ponies playing together in the pasture. " * 8
        xml = f'''\n<?xml version="1.0" encoding="UTF-8"?>
        <rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item>
        <title>Reader Photo Challenge: Draft Horses</title>
        <link>https://www.horsenation.com/2026/10/14/draft-horses/</link>
        <pubDate>{format_datetime(NOW)}</pubDate>
        <content:encoded><![CDATA[<p>{body}</p>]]></content:encoded>
        </item></channel></rss>'''
        parsed = articles.parse_articles(xml.encode())
        self.assertEqual(parsed[0]["source"], "Horse Nation")
        self.assertIsNotNone(articles.choose_article(parsed, NOW))
        parsed[0]["body"] += " Remembering a horse who passed away."
        self.assertIsNone(articles.choose_article(parsed, NOW))

    def test_horse_nation_lookalike_host_is_rejected(self):
        body = "A cute pony plays in a sunny field. " * 10
        xml = f'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item>
        <title>A cute pony</title><link>https://www.horsenation.com.evil.example/story</link>
        <pubDate>{format_datetime(NOW)}</pubDate><content:encoded>{body}</content:encoded>
        </item></channel></rss>'''
        self.assertEqual(articles.parse_articles(xml.encode()), [])


class ArticleCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_feed_timeout_preserves_other_feed_articles(self):
        body = "Enjoy these photos of playful ponies in a sunny field. " * 8
        xml = f'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><item>
        <title>Reader Photo Challenge: Ponies</title><link>https://www.horsenation.com/ponies/</link>
        <pubDate>{format_datetime(NOW)}</pubDate><content:encoded>{body}</content:encoded>
        </item></channel></rss>'''.encode()

        class Response:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def raise_for_status(self):
                pass

            async def read(self):
                return xml

        class Session:
            def get(self, url, **kwargs):
                if "horseandhound" in url:
                    raise TimeoutError("feed unavailable")
                return Response()

        with patch("builtins.print"):
            results = await articles.fetch_articles(Session())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "Horse Nation")

    def context(self, guild_id):
        typing = SimpleNamespace(__aenter__=None)

        class Typing:
            async def __aenter__(self):
                pass

            async def __aexit__(self, *args):
                pass

        status = SimpleNamespace(edit=AsyncMock())
        return SimpleNamespace(guild=SimpleNamespace(id=guild_id), send=AsyncMock(return_value=status), typing=Typing, status=status)

    async def test_server_histories_and_exhaustion(self):
        newest = story("A cute pony makes friends", 1, "one")
        older = story("A playful foal explores a field", 30, "two")
        async def search(session, seen):
            return articles.choose_article([older, newest], seen=seen)

        with tempfile.TemporaryDirectory() as folder, patch.object(articles, "ARTICLE_HISTORY_FILE", Path(folder) / "seen.json"), patch.object(articles, "find_live_article", AsyncMock(side_effect=search)):
            cog = articles.HorseArticles()
            one, two = self.context(1), self.context(2)
            with patch.object(articles, "datetime") as date:
                date.now.return_value = NOW
                await cog.horsearticle.callback(cog, one)
                await cog.horsearticle.callback(cog, one)
                await cog.horsearticle.callback(cog, two)
                await cog.horsearticle.callback(cog, one)
            self.assertEqual(one.status.edit.await_args_list[0].kwargs["embed"].url, newest["url"])
            self.assertEqual(one.status.edit.await_args_list[1].kwargs["embed"].url, older["url"])
            self.assertEqual(two.status.edit.await_args_list[0].kwargs["embed"].url, newest["url"])
            self.assertIn("couldn't find", one.status.edit.await_args_list[2].kwargs["content"])
            self.assertEqual(articles.load_history()["1"], [newest["url"], older["url"]])
            self.assertEqual(articles.load_history()["2"], [newest["url"]])

    async def test_searching_appears_before_search_and_result_edits_it(self):
        current = story("Cute pony finds a friend", 1, "current")
        ctx = self.context(1)

        async def search(session, seen):
            ctx.send.assert_awaited_once()
            self.assertIn("Searching...", ctx.send.call_args.args[0])
            return current

        with tempfile.TemporaryDirectory() as folder, patch.object(articles, "ARTICLE_HISTORY_FILE", Path(folder) / "seen.json"), patch.object(articles, "find_live_article", AsyncMock(side_effect=search)):
            await articles.HorseArticles().horsearticle.callback(articles.HorseArticles(), ctx)
            self.assertEqual(ctx.status.edit.call_args.kwargs["embed"].url, current["url"])

    async def test_failed_result_edit_does_not_mark_seen(self):
        current = story("Cute pony finds a friend", 1, "current")
        ctx = self.context(1)
        ctx.status.edit.side_effect = RuntimeError("Discord unavailable")
        with tempfile.TemporaryDirectory() as folder, patch.object(articles, "ARTICLE_HISTORY_FILE", Path(folder) / "seen.json"), patch.object(articles, "find_live_article", AsyncMock(return_value=current)):
            with self.assertRaises(RuntimeError):
                cog = articles.HorseArticles()
                await cog.horsearticle.callback(cog, ctx)
            self.assertEqual(articles.load_history(), {})

    async def test_search_timeout_replaces_searching_message(self):
        ctx = self.context(1)
        with patch.object(articles, "find_live_article", AsyncMock(side_effect=TimeoutError)), patch("builtins.print"):
            cog = articles.HorseArticles()
            await cog.horsearticle.callback(cog, ctx)
        self.assertIn("Try again", ctx.status.edit.call_args.kwargs["content"])

    async def test_failed_send_does_not_mark_article_seen(self):
        current = story("Cute pony finds a friend", 1, "current")
        with tempfile.TemporaryDirectory() as folder, patch.object(articles, "ARTICLE_HISTORY_FILE", Path(folder) / "seen.json"), patch.object(articles, "fetch_articles", AsyncMock(return_value=[current])):
            cog = articles.HorseArticles()
            ctx = self.context(1)
            ctx.send.side_effect = RuntimeError("Discord unavailable")
            with patch.object(articles, "datetime") as date:
                date.now.return_value = NOW
                with self.assertRaises(RuntimeError):
                    await cog.horsearticle.callback(cog, ctx)
            self.assertEqual(articles.load_history(), {})


if __name__ == "__main__":
    unittest.main()
