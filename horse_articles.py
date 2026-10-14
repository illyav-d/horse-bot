"""Find recent, upbeat horse stories from full-text RSS feeds."""

import asyncio
import html
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlparse
from xml.etree import ElementTree

import aiohttp
import discord
from discord.ext import commands
from data_storage import data_path, write_json


FEEDS = (
    "https://www.horseandhound.co.uk/feed",
    "https://www.horseandhound.co.uk/funny-horse-stuff/feed",
    "https://www.horsenation.com/feed/",
)
SOURCES = {
    "horseandhound.co.uk": "Horse & Hound",
    "www.horseandhound.co.uk": "Horse & Hound",
    "horsenation.com": "Horse Nation",
    "www.horsenation.com": "Horse Nation",
}
ARTICLE_HISTORY_FILE = data_path("HORSE_ARTICLE_FILE", "horse_articles.json")
CONTENT_TAG = "{http://purl.org/dc/elements/1.1/}content"
ENCODED_TAG = "{http://purl.org/rss/1.0/modules/content/}encoded"

# A title must actually sound light. A general mention of a horse is not enough.
CUTE_TITLE = re.compile(
    r"\b(?:cute|adorable|funny|foal|baby|playful|playing|friendship|friends|"
    r"best friend|fell in love|loves?|princess|heartwarming|joyful|delightful|"
    r"sweet|cuddles?|hugs?|naughty|bond|birthday|surprise|charming|cheeky|"
    r"pony.mad|reader photo challenge|the idea of order|tuesday video)\b",
    re.IGNORECASE,
)

# Screen the full feed article, including hidden context beyond the headline.
HEAVY_CONTENT = re.compile(
    r"\b(?:dead|death|deaths|die|died|dies|dying|killed|kill|kills|"
    r"euthanasi[asz]\w*|put (?:him|her|them|the horse|a horse) to sleep|"
    r"passed away|pass away|loss of life|tragic|tragedy|fatal\w*|"
    r"slaughter\w*|abuse\w*|neglect\w*|cruelty|injur\w*|"
    r"suffer\w*|illness\w*|sick|disease\w*|cancer|colic|"
    r"accident\w*|crash\w*|rescue\w*|abandon\w*|memorial|"
    r"remembering|rest easy|rest in peace|farewell)\b",
    re.IGNORECASE,
)


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain_text(markup):
    parser = TextOnly()
    parser.feed(markup or "")
    return re.sub(r"\s+", " ", html.unescape(" ".join(parser.parts))).strip().replace("\ufffd", "'")


def parse_articles(xml_bytes):
    root = ElementTree.fromstring(xml_bytes.strip())
    articles = []
    for item in root.findall("./channel/item"):
        title = plain_text(item.findtext("title"))
        url = (item.findtext("link") or "").strip()
        published = item.findtext("pubDate")
        if not published or not url:
            continue
        parsed_url = urlparse(url)
        if parsed_url.scheme != "https" or parsed_url.hostname not in SOURCES:
            continue
        try:
            published_at = parsedate_to_datetime(published).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        # The feed provides the article body; skip entries without enough text to inspect.
        body = plain_text(item.findtext(CONTENT_TAG) or item.findtext(ENCODED_TAG))
        description = plain_text(item.findtext("description"))
        if len(body) < 200:
            continue
        articles.append({
            "title": title, "url": url, "published": published_at,
            "body": body, "description": description,
            "source": SOURCES[parsed_url.hostname],
        })
    return articles


def choose_article(articles, now=None, seen=()):
    now = now or datetime.now(timezone.utc)
    seen = set(seen)
    eligible = []
    for article in articles:
        age_days = (now - article["published"]).total_seconds() / 86400
        if not 0 <= age_days <= 365 or article["url"] in seen:
            continue
        if not CUTE_TITLE.search(article["title"]):
            continue
        if HEAVY_CONTENT.search(" ".join((article["title"], article["description"], article["body"]))):
            continue
        eligible.append(article)
    return max(eligible, key=lambda article: article["published"], default=None)


def load_history():
    try:
        with ARTICLE_HISTORY_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        print(f"Could not read horse article history: {error}")
        return {}


def save_history(data):
    write_json(ARTICLE_HISTORY_FILE, data)


async def fetch_articles(session):
    async def fetch_feed(url):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "HorsieBot/1.8 (horse story RSS reader)"},
            ) as response:
                response.raise_for_status()
                data = await response.read()
                if len(data) > 2_000_000:
                    return []
            return parse_articles(data)
        except (aiohttp.ClientError, TimeoutError, ValueError, ElementTree.ParseError, UnicodeError) as error:
            print(f"Could not read horse article feed {url}: {error}")
            return []

    batches = await asyncio.gather(*(fetch_feed(url) for url in FEEDS))
    articles = {article["url"]: article for batch in batches for article in batch}
    return list(articles.values())


async def latest_cute_article(session, seen=()):
    return choose_article(await fetch_articles(session), seen=seen)


class HorseArticles(commands.Cog):
    def __init__(self):
        self.locks = {}

    @commands.command(name="horsearticle")
    @commands.cooldown(1, 15, commands.BucketType.user)
    @commands.guild_only()
    async def horsearticle(self, ctx):
        """Find the latest light horse story: !horsearticle."""
        try:
            async with ctx.typing(), aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                articles = await fetch_articles(session)
        except (aiohttp.ClientError, TimeoutError) as error:
            print(f"Could not fetch horse article: {error}")
            await ctx.send("🐴 The horse news is taking a nap. Try again later.")
            return
        async with self.locks.setdefault(ctx.guild.id, asyncio.Lock()):
            history = load_history()
            server_key = str(ctx.guild.id)
            seen = history.get(server_key, [])
            if not isinstance(seen, list):
                seen = []
            article = choose_article(articles, seen=seen)
            if article is None:
                await ctx.send("🐴 I've run out of fresh, happy horse stories for this server. Try again when there's a new one.")
                return
            embed = discord.Embed(
                title=article["title"][:256], url=article["url"],
                description=(article["description"] or article["body"])[:300],
                colour=0xE8B86D,
            )
            embed.set_footer(text="Horse & Hound • Picked from recent articles")
            embed.timestamp = article["published"]
            await ctx.send("🐴 Found a nice horse story:", embed=embed, allowed_mentions=discord.AllowedMentions.none())
            history[server_key] = (seen + [article["url"]])[-200:]
            try:
                save_history(history)
            except OSError as error:
                print(f"Could not save horse article history: {error}")

    @horsearticle.error
    async def horsearticle_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"🐴 Give me {error.retry_after:.0f} seconds to finish reading.")
        else:
            raise error


if __name__ == "__main__":
    async def check_feed():
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            article = await latest_cute_article(session)
            print(article["title"] if article else "No suitable recent horse article")

    asyncio.run(check_feed())
