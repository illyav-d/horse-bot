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


class ArticleCommandTests(unittest.IsolatedAsyncioTestCase):
    def context(self, guild_id):
        typing = SimpleNamespace(__aenter__=None)

        class Typing:
            async def __aenter__(self):
                pass

            async def __aexit__(self, *args):
                pass

        return SimpleNamespace(guild=SimpleNamespace(id=guild_id), send=AsyncMock(), typing=Typing)

    async def test_server_histories_and_exhaustion(self):
        newest = story("A cute pony makes friends", 1, "one")
        older = story("A playful foal explores a field", 30, "two")
        with tempfile.TemporaryDirectory() as folder, patch.object(articles, "ARTICLE_HISTORY_FILE", Path(folder) / "seen.json"), patch.object(articles, "fetch_articles", AsyncMock(return_value=[older, newest])):
            cog = articles.HorseArticles()
            one, two = self.context(1), self.context(2)
            with patch.object(articles, "datetime") as date:
                date.now.return_value = NOW
                await cog.horsearticle.callback(cog, one)
                await cog.horsearticle.callback(cog, one)
                await cog.horsearticle.callback(cog, two)
                await cog.horsearticle.callback(cog, one)
            self.assertEqual(one.send.await_args_list[0].kwargs["embed"].url, newest["url"])
            self.assertEqual(one.send.await_args_list[1].kwargs["embed"].url, older["url"])
            self.assertEqual(two.send.await_args_list[0].kwargs["embed"].url, newest["url"])
            self.assertIn("run out", one.send.await_args_list[2].args[0])
            self.assertEqual(articles.load_history()["1"], [newest["url"], older["url"]])
            self.assertEqual(articles.load_history()["2"], [newest["url"]])

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
