"""Read public horse archive and article pages without including site sidebars."""

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp


SOURCES = {
    "horseandhound.co.uk": "Horse & Hound",
    "www.horseandhound.co.uk": "Horse & Hound",
    "horsenation.com": "Horse Nation",
    "www.horsenation.com": "Horse Nation",
}
HEADERS = {"User-Agent": "HorsieBot/1.8 (horse story reader)"}
MAX_PAGE_BYTES = 3_000_000
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def normalize_url(url):
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname in SOURCES
                 and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except (ValueError, TypeError):
        return None
    if not valid:
        return None
    host = "www." + parsed.hostname.removeprefix("www.")
    path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/") or "/"
    return urlunsplit(("https", host, path, "", ""))


class ArchiveLinks(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url, self.href, self.parts, self.links = base_url, None, [], []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href, self.parts = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self.href:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            url = normalize_url(urljoin(self.base_url, self.href))
            title = " ".join(" ".join(self.parts).split())
            if url and len(title.split()) >= 3:
                path = urlsplit(url).path
                if not re.search(r"/(?:page|tag|category|author|feed)(?:/|$)", path):
                    self.links.append({"title": title, "url": url})
            self.href = None


class ArticlePage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.body, self.metadata, self.structured = [], [], {}, []
        self.body_depth = None
        self.json_parts = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
            if key:
                self.metadata[key.lower()] = attrs.get("content", "")
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.json_parts = []
        classes = attrs.get("class", "").split()
        excluded = tag in {"script", "style", "nav", "aside", "footer", "form"} or any(
            re.search(r"related|newsletter|advert|author-bio|comment|social-share", value)
            for value in classes
        )
        if tag not in VOID_TAGS:
            self.stack.append((tag, excluded))
            if self.body_depth is None and (attrs.get("id") == "article-body" or "entry-content" in classes):
                self.body_depth = len(self.stack)
        if tag == "img" and self.body_depth and not any(skip for _, skip in self.stack):
            self.body.append(attrs.get("alt", ""))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "script" and self.json_parts is not None:
            try:
                self.structured.append(json.loads("".join(self.json_parts)))
            except ValueError:
                pass
            self.json_parts = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                if self.body_depth and len(self.stack) < self.body_depth:
                    self.body_depth = None
                break

    def handle_data(self, data):
        if self.json_parts is not None:
            self.json_parts.append(data)
        if self.body_depth and not any(skip for _, skip in self.stack):
            self.body.append(data)


def structured_articles(value):
    if isinstance(value, list):
        for item in value:
            yield from structured_articles(item)
    elif isinstance(value, dict):
        types = value.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if any(kind in {"Article", "NewsArticle", "BlogPosting"} for kind in types):
            yield value
        yield from structured_articles(value.get("@graph", []))


def parse_page(markup, url):
    url = normalize_url(url)
    if not url:
        return None
    parser = ArticlePage()
    parser.feed(markup)
    structured = next(structured_articles(parser.structured), {})
    if str(structured.get("isAccessibleForFree", "true")).lower() == "false":
        return None
    title = structured.get("headline") or parser.metadata.get("og:title")
    published = structured.get("datePublished") or parser.metadata.get("article:published_time") or parser.metadata.get("datepublished")
    if not isinstance(title, str) or not isinstance(published, str):
        return None
    try:
        date = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    body = " ".join(" ".join(parser.body).split())
    if len(body) < 200:
        return None
    return {
        "url": url, "title": " ".join(title.split()), "published": date,
        "body": body,
        "description": parser.metadata.get("og:description") or parser.metadata.get("description", ""),
        "source": SOURCES[urlsplit(url).hostname],
    }


async def fetch_html(session, url, semaphore):
    """Follow only redirects to approved public publishers."""
    try:
        url = normalize_url(url)
        async with semaphore:
            for _ in range(4):
                if not url:
                    return None
                async with session.get(url, headers=HEADERS, allow_redirects=False,
                                       timeout=aiohttp.ClientTimeout(total=8)) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        destination = urljoin(url, response.headers.get("Location", ""))
                        if not normalize_url(destination):
                            return None
                        url = destination
                        continue
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in response.content.iter_chunked(65_536):
                        size += len(chunk)
                        if size > MAX_PAGE_BYTES:
                            return None
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    return raw.decode(response.charset or "utf-8", errors="replace"), normalize_url(url)
    except (aiohttp.ClientError, TimeoutError, ValueError, LookupError) as error:
        print(f"Could not read horse page {url}: {error}")
    return None
