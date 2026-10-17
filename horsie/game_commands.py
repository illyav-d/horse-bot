"""On-demand game API commands. No Discord connection is made on import."""

import asyncio
import re
import statistics
import time
from urllib.parse import quote

import aiohttp
import discord
from discord.ext import commands


class GameAPIError(Exception):
    """An error suitable for displaying in Discord, without credentials."""


async def request_json(session, method, url, **kwargs):
    async with session.request(method, url, **kwargs) as response:
        if response.status == 404:
            raise GameAPIError("Nothing found. Check the character, realm/world, or item name.")
        if response.status == 429:
            raise GameAPIError("That service is rate limited. Please try again later.")
        if response.status in (401, 403):
            raise GameAPIError("The service denied access. The character may be unavailable or hidden.")
        if response.status >= 400:
            raise GameAPIError("The game API is unavailable right now. Please try again later.")
        data = await response.json()
        if not isinstance(data, dict):
            raise GameAPIError("The game API returned an unexpected response.")
        return data


def clean(value, limit=200):
    return discord.utils.escape_markdown(str(value))[:limit]


def summarize_sales(entries, now):
    """Compare like-quality sales in two adjacent 24-hour windows, per unit."""
    valid = [e for e in entries if e.get("pricePerUnit", 0) > 0
             and e.get("quantity", 0) > 0 and now - 172800 <= e.get("timestamp", 0) <= now]
    recent = [e for e in valid if e["timestamp"] >= now - 86400]
    previous = [e for e in valid if e["timestamp"] < now - 86400]
    return {
        "recent_count": len(recent),
        "previous_count": len(previous),
        "recent_median": statistics.median(e["pricePerUnit"] for e in recent) if recent else None,
        "previous_median": statistics.median(e["pricePerUnit"] for e in previous) if previous else None,
        "units": sum(e["quantity"] for e in recent),
        "latest": max((e["timestamp"] for e in valid), default=None),
    }


class GameCommands(commands.Cog):
    def __init__(self, bot, find_item):
        self.bot = bot
        self.find_item = find_item

    @commands.command(name="wow", ignore_extra=False)
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def wow(self, ctx, region: str, realm: str, character: str):
        """Retail character card: !wow eu silvermoon Name. Quote realms with spaces."""
        region = region.lower()
        if region not in {"eu", "us", "kr", "tw"}:
            raise GameAPIError("Region must be `eu`, `us`, `kr`, or `tw`.")
        async with ctx.typing(), aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            data = await request_json(session, "GET", "https://raider.io/api/v1/characters/profile", params={
                "region": region, "realm": realm, "name": character,
                "fields": "gear,mythic_plus_scores_by_season:current,raid_progression",
            })
            embed = discord.Embed(title=clean(f"{data['name']} — {data['realm']}"), url=data["profile_url"], colour=0xE6B422)
            embed.description = clean(f"{data.get('race', '')} {data.get('active_spec_name', '')} {data.get('class', '')}")
            if data.get("thumbnail_url"):
                embed.set_thumbnail(url=data["thumbnail_url"])
            gear = data.get("gear") or {}
            embed.add_field(name="Equipped item level", value=str(gear.get("item_level_equipped", "Unavailable")))
            seasons = data.get("mythic_plus_scores_by_season") or []
            score = seasons[0].get("scores", {}).get("all", "Unavailable") if seasons else "Unavailable"
            embed.add_field(name="Current Mythic+ score", value=str(score))
            raids = data.get("raid_progression") or {}
            progress = "\n".join(f"{clean(name)}: {clean(info.get('summary', 'Unavailable'))}" for name, info in raids.items())
            embed.add_field(name="Raid progression", value=progress[:1024] or "No progression reported.", inline=False)
            embed.set_footer(text="Raider.IO • Cached character data; not a live in-game feed.")
            await ctx.send(embed=embed)

    @commands.command(name="xivtrend")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def xivtrend(self, ctx, world: str, *, item: str):
        """Price trends: !xivtrend Light Yollal Extract [--hq|--nq]. Defaults to NQ."""
        quality = "nq"
        quality_match = re.search(r"\s+--(hq|nq)$", item, re.I)
        if quality_match:
            quality = quality_match[1].lower()
            item = item[:quality_match.start()].strip()
        async with ctx.typing():
            found = await self.find_item(item)
            if not found:
                raise GameAPIError("Item not found. Try its full FFXIV name.")
            item_id, item_name = found
            base = f"https://universalis.app/api/v2/{quote(world, safe='')}/{item_id}"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
                data = await request_json(session, "GET", base, params={"listings": 20, "entries": 0, "hq": quality == "hq" and "true" or "false"})
                history = await request_json(session, "GET", f"https://universalis.app/api/v2/history/{quote(world, safe='')}/{item_id}", params={"entries": 1000, "entriesWithin": 172800, "hq": quality == "hq" and "true" or "false"})
            entries = [e for e in history.get("entries", []) if bool(e.get("hq", False)) == (quality == "hq")]
            stats = summarize_sales(entries, time.time())
            listings = [l for l in data.get("listings", []) if l.get("pricePerUnit", 0) > 0 and bool(l.get("hq", False)) == (quality == "hq")]
            embed = discord.Embed(title=clean(f"{item_name} ({quality.upper()}) — {world}", 256), url=f"https://universalis.app/market/{item_id}", colour=0x2ECC71)
            if listings:
                listing = min(listings, key=lambda l: l["pricePerUnit"])
                embed.add_field(name="Cheapest listed / item", value=f"{listing['pricePerUnit']:,} gil\n{clean(listing.get('worldName') or data.get('worldName') or world)}")
                if stats["recent_median"]:
                    difference = (listing["pricePerUnit"] / stats["recent_median"] - 1) * 100
                    embed.add_field(name="Listing vs 24h sale median", value=f"{difference:+.1f}%")
            else:
                embed.add_field(name="Current listings", value="No listings available for this quality.")
            for label, median, count in [("Last 24h", stats["recent_median"], stats["recent_count"]), ("Previous 24h", stats["previous_median"], stats["previous_count"])]:
                value = f"{median:,.0f} gil/item median\n{count} observed sales" if median is not None else "No observed sales"
                embed.add_field(name=label, value=value)
            if stats["recent_count"] >= 3 and stats["previous_count"] >= 3:
                change = (stats["recent_median"] / stats["previous_median"] - 1) * 100
                embed.add_field(name="Median price change", value=f"{change:+.1f}% versus previous 24h")
            else:
                embed.add_field(name="Trend", value="Too few sales to compare (need 3 in each window).")
            embed.add_field(name="Observed units sold (24h)", value=f"{stats['units']:,}")
            if stats["latest"]:
                embed.add_field(name="Latest observed sale", value=f"<t:{int(stats['latest'])}:R>")
            if data.get("lastUploadTime"):
                embed.add_field(name="Listings updated", value=f"<t:{int(data['lastUploadTime'] / 1000)}:R>")
            embed.set_footer(text="Universalis • Community uploads; up to 1,000 sales sampled over 48h. Sale medians weight each transaction equally.")
            await ctx.send(embed=embed)

    async def cog_command_error(self, ctx, error):
        original = getattr(error, "original", error)
        if isinstance(original, GameAPIError):
            message = str(original)
        elif isinstance(error, commands.CommandOnCooldown):
            message = f"Please wait {error.retry_after:.0f} seconds before using this command again."
        elif isinstance(error, commands.UserInputError):
            message = f"Usage: `!{ctx.command.qualified_name} {ctx.command.signature}`\n{ctx.command.help}"
        elif isinstance(original, (aiohttp.ClientError, asyncio.TimeoutError)):
            message = "The game API did not respond correctly. Please try again shortly."
        elif isinstance(original, (KeyError, TypeError, ValueError)):
            message = "The game API returned incomplete data. Please try again later."
        else:
            raise error
        await ctx.send(message, allowed_mentions=discord.AllowedMentions.none())
