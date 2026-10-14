import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import horse_articles as articles
from horse_web import ArchiveLinks, fetch_html, normalize_url, parse_page
from test_horse_articles import NOW, story


URL = "https://www.horsenation.com/2026/10/14/cute-pony"


def page(body=None, paywall=False):
    body = body or "The playful pony enjoys a sunny field with its friends. " * 8
    return f'''<html><head><meta property="og:title" content="A cute pony makes friends">
    <meta property="article:published_time" content="{NOW.isoformat()}">
    <script type="application/ld+json">{{"@type":"NewsArticle","isAccessibleForFree":{str(not paywall).lower()}}}</script>
    </head><body><nav>A horse died.</nav><div class="entry-content"><p>{body}</p>
    <aside>A horse was injured.</aside><div class="related-posts">More sad stories about death.</div>
    </div><footer>A horse was killed.</footer></body></html>'''


class PageTests(unittest.TestCase):
    def test_article_body_excludes_navigation_related_posts_and_footer(self):
        result = parse_page(page(), URL)
        self.assertEqual(result["source"], "Horse Nation")
        self.assertEqual(result["published"], NOW)
        self.assertIsNotNone(articles.choose_article([result], NOW))
        self.assertNotIn("injured", result["body"])

    def test_heavy_full_page_is_rejected_despite_cute_title(self):
        result = parse_page(page("The playful pony was injured. " * 15), URL)
        self.assertIsNone(articles.choose_article([result], NOW))

    def test_paywall_missing_date_and_short_text_are_rejected(self):
        self.assertIsNone(parse_page(page(paywall=True), URL))
        self.assertIsNone(parse_page(page().replace("article:published_time", "unknown"), URL))
        self.assertIsNone(parse_page(page("Hi!"), URL))

    def test_archive_links_and_url_identity(self):
        parser = ArchiveLinks("https://www.horsenation.com/page/2/")
        parser.feed(f'<a href="{URL}/?utm_source=feed"><span>A cute pony</span> makes friends</a>'
                    '<a href="https://evil.example/pony">A cute pony story</a>')
        self.assertEqual(parser.links, [{"title": "A cute pony makes friends", "url": URL}])
        self.assertEqual(normalize_url(URL + "/?utm_source=feed"), URL)
        self.assertIsNone(normalize_url("https://www.horsenation.com:bad/story"))
        self.assertIsNone(normalize_url("https://user@www.horsenation.com/story"))


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_feed_exhaustion_discovers_and_reads_an_archive_article(self):
        calls = []

        async def html(session, url, semaphore):
            calls.append(url)
            if url == URL:
                return page(), url
            return f'<a href="{URL}">A cute pony makes friends</a>', url

        with patch.object(articles, "fetch_articles", AsyncMock(return_value=[])), patch.object(articles, "fetch_html", side_effect=html), patch.object(articles, "datetime") as clock:
            clock.now.return_value = NOW
            result = await articles.find_live_article(None)
        self.assertEqual(result["url"], URL)
        self.assertTrue(any("/page/" in url for url in calls))
        self.assertIn(URL, calls)

    async def test_happy_feed_cannot_override_heavy_article_page(self):
        recent = story("A cute pony makes friends", 1, "cute")

        async def html(session, url, semaphore):
            if url == recent["url"]:
                return page("The cute pony was injured. " * 20), url
            return None

        with patch.object(articles, "fetch_articles", AsyncMock(return_value=[recent])), patch.object(articles, "fetch_html", side_effect=html), patch.object(articles, "datetime") as clock:
            clock.now.return_value = NOW
            self.assertIsNone(await articles.find_live_article(None))

    async def test_streamed_pages_are_fully_read_and_external_redirects_blocked(self):
        class Content:
            async def iter_chunked(self, size):
                yield b"<html>"
                yield b"the entire article</html>"

        class Response:
            status, charset = 200, "utf-8"
            headers = {}
            content = Content()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def raise_for_status(self):
                pass

        class Session:
            def __init__(self):
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append(url)
                return Response()

        session = Session()
        result = await fetch_html(session, URL, asyncio.Semaphore(1))
        self.assertEqual(result[0], "<html>the entire article</html>")
        with patch.object(Response, "status", 302), patch.object(Response, "headers", {"Location": "http://127.0.0.1/private"}):
            self.assertIsNone(await fetch_html(session, URL, asyncio.Semaphore(1)))
        self.assertEqual(len(session.calls), 2)

    async def test_publisher_trailing_slash_redirect_is_followed(self):
        class Response:
            charset = "utf-8"

            def __init__(self, url):
                self.status = 200 if url.endswith("/") else 301
                self.headers = {"Location": URL + "/"}
                self.content = self

            async def iter_chunked(self, size):
                yield b"complete page"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def raise_for_status(self):
                pass

        class Session:
            def get(self, url, **kwargs):
                return Response(url)

        self.assertEqual(await fetch_html(Session(), URL, asyncio.Semaphore(1)), ("complete page", URL))


if __name__ == "__main__":
    unittest.main()
