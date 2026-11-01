import os
import random
import asyncio
import json
import re
import uuid
from contextlib import closing
from urllib.parse import quote
import aiohttp
import discord
from discord.ext import commands, tasks
from datetime import datetime, time, timezone
from horsie.bot_text import line
from horsie.horse_reactions import HorseReactions
from horsie.horse_articles import HorseArticles
from horsie.reality_check import RealityCheck
from horsie.horse_chat import HorseChat
from horsie.game_commands import GameCommands
from horsie.race_betting import collect_race_bets, winner_pages
from horsie.data_storage import ASSETS_DIR, data_path, write_json
from horsie.discord_startup import run_bot
from horsie.changelog_history import ChangelogHistory

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Safety cap for !trample all.
# You can change this in your environment variables if needed.
TRAMPLE_ALL_MAX_MESSAGES = int(os.getenv("TRAMPLE_ALL_MAX_MESSAGES", "1000"))

# Local save file for carrot points.
# This keeps scores even after the bot restarts.
CARROT_FILE = data_path("CARROT_FILE", "carrots.json")

# Local save file for the WoW Forever countdown channel.
# This lets the countdown resume automatically after a bot restart.
FOREVER_CONFIG_FILE = data_path("FOREVER_CONFIG_FILE", "forever_countdown.json")

# Local save file for FFXIV Universalis market watches.
XIV_WATCH_FILE = data_path("XIV_WATCH_FILE", "xiv_watches.json")
CHANGELOG_HISTORY_FILE = data_path("CHANGELOG_HISTORY_FILE", "changelog_history.json")

# WoW Forever launch: 5 November 2026 at 00:00 Belgian time (CET).
# Stored as UTC to keep the countdown timezone-safe.
WOW_FOREVER_LAUNCH = datetime(2026, 11, 4, 23, 0, 0, tzinfo=timezone.utc)

FOREVER_CHANNEL_PATTERN = re.compile(
    r"^wow-forever-(?:\d+d-\d{2}h|\d{2}h-\d{2}m|\d{2}m|live)$",
    re.IGNORECASE,
)

VERSION = "1.8.9"

CHANGELOG = [
    "Mention or reply to chat with Horsie; web search is disabled.",
]


HORSE_IMAGES = [
    'https://i.imgur.com/LgWcwzG.png',
    'https://static.klipy.com/ii/4e7bea9f7a3371424e6c16ebc93252fe/ac/03/JQLCKiGA4E2v82LN.gif',
    'https://i.imgur.com/h0Lk1ti.gif',
    'https://i.imgur.com/t1GTp5l.gif',
    'https://i.imgur.com/88Fawk4.gif',
    'https://i.imgur.com/d5llZZb.gif',
    'https://t4.ftcdn.net/jpg/02/94/38/37/240_F_294383771_S19Z1L8xqo2Gii4wF3o4CssWpKS64M5N.jpg',
    'https://media.istockphoto.com/id/2057941107/photo/horse-with-curious-smile.jpg',
    'https://media.istockphoto.com/id/1300980030/photo/curious-brown-colt-looks-into-camera-while-grazing-on-a-sunny-day.jpg',
]

HORSE_FACTS = [
    'Horses are herbivores.',
    'A baby horse is called a foal.',
    'A young female horse is called a filly.',
    'A young male horse is called a colt.',
    'An adult male horse is called a stallion.',
    'A castrated male horse is called a gelding.',
    'Ponies are not baby horses.',
    'Horses can sleep standing up.',
    'Horses can also lie down to sleep.',
    'Horses are social animals.',
    'Horses often form bonds with other horses.',
    'Horses are prey animals.',
    'Many horses react first by trying to flee.',
    'Horses use body language to communicate.',
    'Horse ears can move independently.',
    'Horse ears can show mood and attention.',
    'Horses have large eyes.',
    "A horse's eyes are on the sides of its head.",
    'Horses have a very wide field of vision.',
    'Horses have small blind spots in front and behind.',
    'Horses are good at noticing movement.',
    'Horses have strong hearing.',
    'Horses have a strong sense of smell.',
    'Horses often sniff unfamiliar things first.',
    'Horses breathe through their noses.',
    "A horse's stomach is relatively small.",
    'Horses are built to graze throughout the day.',
    'Horses are hindgut fermenters.',
    'Much of their digestion happens in the cecum and colon.',
    'Horses do poorly with sudden diet changes.',
    'Horses generally cannot vomit.',
    'Regular forage is important for horses.',
    'Hooves are made of keratin.',
    'Horse teeth continue to erupt through much of life.',
    'Dental care matters for horses.',
    "A horse's coat can change with the seasons.",
    'Some horses grow a thicker winter coat.',
    'The mane is the longer hair on the neck.',
    'The tail helps swat away flies.',
    'Foals can stand very soon after birth.',
    'Foals usually nurse from their mothers.',
    'Horses can learn through repetition.',
    'Many horses recognize familiar people.',
    'Horses can become stressed if isolated.',
    'Grooming can help build trust.',
    'Different horse breeds were developed for different jobs.',
    'Humans have used horses for travel, farming, sport, and companionship.',
    'Some horses love routine.',
    'Horses can show curiosity toward new objects.',
    'This horse believes in you.',
    'Due to the placement of their eyes, horses possess an impressive 340 to 350-degree range of vision.',
    'While humans have only three ear muscles, horses have 10, allowing them to rotate their ears 180 degrees independently.',
    'Male horses are among the very few male mammals that do not possess nipples.',
    "A horse's brain weighs only about 22 ounces, which is roughly half the weight of a human brain.",
    'Horses do not produce saliva automatically and must chew to generate it, producing up to 11 gallons daily.',
    'Just like humans, equines with pale pink skin can easily get a painful sunburn.',
    "Foals are born with a soft, rubbery layer over their hooves to protect the mother's birth canal from injury.",
    "An adult horse's heart weighs between 8.5 and 10 pounds, roughly matching the size of a basketball.",
    'Horses can read human facial expressions and remember your past emotional state.',
    'Certain heavily feathered draft breeds, like the Gypsy Vanner, are genetically capable of growing full mustaches.',
    'When horses curl up their upper lip to look like they are laughing, they are actually gathering scents.',
    "Studies show that pumping lavender-scented air into a stable significantly lowers a horse's elevated heart rate.",
    'The earliest ancestor of the horse was the Eohippus, a small jungle creature the size of a Golden Retriever.',
    'Over millions of years of evolution, horses shifted from walking on multiple toes to standing entirely on a single central digit.',
    'The longest-living horse on official record was named Old Billy, who survived to the remarkable age of 62.',
    # Sources for the additions below: HORSE_FACT_SOURCES.md.
    'A horse\'s whiskers are sensory hairs, not just impressive facial decorations.',
    'Whiskers help horses sense objects in the blind spots right around their muzzle.',
    'The follicles around horse whiskers have more nerve connections than ordinary hair follicles.',
    'Whiskers around a horse\'s eyelids can trigger a protective blink when they touch something.',
    'Horses can use their whiskers to investigate the texture of food.',
    'A horse\'s walk has a four-beat rhythm: each hoof lands separately.',
    'A trot has two beats, with the legs moving in diagonal pairs.',
    'In a trot, the left front and right hind legs move as a pair, then the other diagonal pair follows.',
    'A canter normally has a three-beat rhythm.',
    'A gallop has four beats, unlike the usual three beats of a canter.',
    'Horse coats have three basic colour backgrounds: chestnut, bay, and black.',
    'Bay horses have a brownish body with black points, including the mane and tail.',
    'Chestnut horses have reddish coats and do not have true black points.',
    'A palomino has a golden coat with a light-coloured mane and tail.',
    'A white marking on a horse\'s forehead is called a star, even when it is not star-shaped.',
    'A small white marking around a horse\'s muzzle is called a snip.',
    'White markings on a horse\'s legs are often described as socks or stockings.',
    'Grey horses can be born dark and grow more white hairs as they age.',
    'Lipizzan horses are usually born dark, even though many become nearly white as adults.',
    'The UK Shetland Pony Stud-Book Society sets an adult height limit of 42 inches, or about 107 centimetres.',
    'In the UK Shetland breed registry, ponies measuring 34 inches or less are classed as Miniatures.',
    'Shetland ponies are used for driving carriages as well as for riding.',
    'A winter coat helps a horse stay warm by trapping a layer of air close to its body.',
    'Changes in daylight help control when horses grow and shed their seasonal coats.',
    'Microbes fermenting forage in a horse\'s gut produce heat, helping keep the horse warm.',
    'Horses groom one another, using their teeth to scratch places a friend cannot easily reach.',
    'Horses can recognise a familiar person by combining information from their face and voice.',
    'Experiments have shown that horses respond to emotional cues in human voices as well as faces.',
    'Horses can also respond differently to different human body postures.',
    'Horse welfare groups describe three everyday essentials as the three Fs: friends, forage, and freedom.',
]

HORSE_RACE_NAMES = [
    "Sir Neighs-a-Lot",
    "Hoof Hearted",
    "Hay Fever",
    "Stable Genius",
    "Mane Attraction",
    "Usain Colt",
    "Harry Trotter",
    "Neighoncé",
    "Pony Soprano",
    "Clip Clop Champion",
    "Gallopagos",
    "The Fast and the Furriest",
    "Saddle McSaddleface",
    "Trotty McTrotface",
    "Mister Edgelord",
    "Haystack Hero",
    "Glue Factory Escapee",
    "Lord of the Reins",
    "Bridle Gossip",
    "Hoofington III",
    "Count Clipula",
    "Mare-y Poppins",
    "The Neigh Sayer",
    "Carrot Goblin",
    "Sir Canterlot",
    "Gallop Poll",
    "Barn Vader",
    "The Foal Package",
    "Nightmare Fuel",
    "Pasture Prime",
]

HORSE_RACE_STARTS = [
    "🏁 The gate explodes open and the horses launch themselves into questionable life choices!",
    "🏁 They're off! One horse immediately looks surprised to be employed.",
    "🏁 The race begins! Hooves thunder, spectators scream, and one pigeon files a complaint.",
    "🏁 The herd charges forward with the confidence of animals that cannot read warning signs.",
    "🏁 The starting bell rings and four athletes with zero financial responsibility begin sprinting!",
    "🏁 They're off! The track trembles, the crowd roars, and the carrots look nervous.",
]

HORSE_RACE_EVENTS = [
    "🐎 {horse} surges ahead after remembering there might be snacks at the finish line!",
    "🪣 {horse} gets distracted by a suspicious bucket but somehow keeps running.",
    "💨 {horse} finds a second wind. It smells faintly of hay and ambition.",
    "🧲 {horse} drifts toward the fence like it has been magnetized by bad decisions.",
    "🥕 {horse} spots a carrot in the crowd and achieves temporary enlightenment.",
    "🌪️ {horse} kicks up dust and briefly becomes a weather event.",
    "🎺 {horse} hears imaginary victory music and starts showing off.",
    "🐌 {horse} slows down to consider the meaning of grass.",
    "🛞 {horse} takes the corner wide, possibly obeying traffic laws.",
    "👀 {horse} makes intense eye contact with the audience. Nobody feels safe.",
    "🦆 A duck crosses the track. {horse} politely gives it right of way.",
    "📣 The announcer mispronounces {horse}'s name and the horse takes it personally.",
    "🍎 {horse} receives an emotional boost from the concept of apples.",
    "🧠 {horse} appears to form a strategy, then immediately forgets it.",
    "🚀 {horse} accelerates like someone whispered 'vet appointment' behind them.",
    "🧹 {horse} nearly trips over a broom that absolutely was not there before.",
    "🐴 {horse} neighs dramatically and the other horses pretend not to be impressed.",
    "🕺 {horse} breaks into what might be dressage or might be panic.",
    "📦 {horse} notices a cardboard box and questions its entire career.",
    "🧀 {horse} takes a risky inside line, also known as 'the cheese route' for unknown reasons.",
    "🎲 {horse} is now moving randomly but with great confidence.",
    "🌽 {horse} hears someone say 'corn' and briefly changes lanes.",
    "🚧 {horse} jumps over absolutely nothing. Style points awarded.",
    "🥁 {horse} matches its hoofbeats to an imaginary drum solo.",
    "🧃 {horse} pauses spiritually, not physically, for a juice break.",
    "🕳️ {horse} avoids a pothole that only it can see.",
    "🦄 {horse} tries to manifest a unicorn horn through sheer self-belief.",
    "🪩 {horse} enters disco mode. Speed uncertain, vibes undeniable.",
    "🛒 {horse} cuts across the track like a shopping cart with one bad wheel.",
    "🎩 {horse} runs with the dignity of a tiny mayor.",
    "📉 {horse} loses momentum after thinking about taxes.",
    "📈 {horse} gains momentum after deciding taxes are not real.",
    "🥔 {horse} is briefly mistaken for a potato with legs, which is motivating somehow.",
    "🧼 {horse} slips slightly, recovers, and blames the soap industry.",
    "🐝 A bee enters the arena. {horse} suddenly discovers maximum speed.",
    "🪄 {horse} performs what experts are calling 'probably not magic'.",
]

HORSE_RACE_FINAL_EVENTS = [
    "🔥 The final stretch is pure chaos!",
    "📸 The finish line camera is sweating.",
    "🥁 The crowd is stomping, the horses are snorting, and destiny is chewing hay.",
    "⚡ One last burst of speed shakes the entire pasture!",
    "🏇 The horses are neck and neck, hoof and hoof, nonsense and nonsense!",
    "🥕 The carrot economy holds its breath.",
    "🌩️ The final meters feel illegal in several jurisdictions.",
]

HORSE_RUN_TRACK_LENGTH = 18

HORSE_RUN_EVENTS = [
    ("🥕 {horse} found a carrot boost and bolts forward!", 2),
    ("🪣 {horse} stopped to investigate a bucket. Terrible priorities.", -1),
    ("🐝 A bee appears. {horse} discovers emergency speed!", 3),
    ("🧼 {horse} slips on suspicious stable soap.", -2),
    ("🚀 {horse} hears 'vet appointment' and launches forward!", 3),
    ("🌽 {horse} gets distracted by corn-based thoughts.", -1),
    ("🪄 {horse} uses probably-not-legal horse magic.", 2),
    ("🛒 {horse} moves like a shopping cart with one cursed wheel.", -1),
    ("🎺 {horse} hears victory music and gains confidence.", 2),
    ("🥔 {horse} is mistaken for a potato and takes that personally.", 1),
    ("🦆 A duck crosses the lane. {horse} politely slows down.", -1),
    ("🕳️ {horse} avoids an invisible pothole with heroic drama.", 1),
]

HORSEJACK_DEALER_REACTIONS = [
    "The dealer horse adjusts its tiny visor.",
    "The dealer horse chews the corner of the rulebook.",
    "The dealer horse stares at the cards like they owe it money.",
    "The dealer horse snorts with suspicious confidence.",
]

FACT_QUEUE = []

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
startup_announced = False


def load_carrots():
    if not CARROT_FILE.exists():
        return {}

    try:
        with CARROT_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as error:
        # Do not overwrite a damaged scoreboard with an empty one after a win.
        raise RuntimeError(f"Carrot save {CARROT_FILE} is invalid; restore a backup.") from error


def save_carrots(data):
    write_json(CARROT_FILE, data)


def load_forever_config():
    if not FOREVER_CONFIG_FILE.exists():
        return {}

    try:
        with FOREVER_CONFIG_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        print(f"Could not read {FOREVER_CONFIG_FILE}: {error}")
        return {}

    if not isinstance(data, dict):
        return {}

    return data


def save_forever_config(guild_id, channel_id):
    data = load_forever_config()
    data.setdefault("channels", {})[str(guild_id)] = int(channel_id)
    FOREVER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    with FOREVER_CONFIG_FILE.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


def get_forever_channel_id(guild):
    data = load_forever_config()

    try:
        channel_id = int(data.get("channels", {}).get(str(guild.id), 0))
        if channel_id:
            return channel_id
        legacy_id = int(data.get("channel_id", 0))
        return legacy_id if guild.get_channel(legacy_id) is not None else 0
    except (TypeError, ValueError):
        return 0


def find_existing_forever_countdown_channel(guild):
    """Find an existing WoW Forever countdown channel by its generated name."""
    for channel in guild.text_channels:
        if FOREVER_CHANNEL_PATTERN.fullmatch(channel.name):
            return channel

    return None



def load_xiv_watches():
    if not XIV_WATCH_FILE.exists():
        return []

    try:
        with XIV_WATCH_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        print(f"Could not read {XIV_WATCH_FILE}: {error}")
        return []

    if not isinstance(data, list):
        return []

    return data


def save_xiv_watches(watches):
    XIV_WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)

    with XIV_WATCH_FILE.open("w", encoding="utf-8") as file:
        json.dump(watches, file, indent=4)


async def find_xiv_item(item_name):
    """Resolve a typed FFXIV item name to an XIVAPI item ID."""
    safe_name = item_name.replace("\\", "\\\\").replace('"', '\\"')

    params = {
        "sheets": "Item",
        "query": f'Name~"{safe_name}"',
        "fields": "Name",
        "limit": 10,
    }

    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            "https://v2.xivapi.com/api/search",
            params=params,
        ) as response:
            response.raise_for_status()
            data = await response.json()

    results = data.get("results", [])

    if not results:
        return None

    # Prefer an exact case-insensitive match when XIVAPI returns one.
    for result in results:
        name = result.get("fields", {}).get("Name", "")
        if name.casefold() == item_name.casefold():
            return int(result["row_id"]), name

    # Otherwise use XIVAPI's highest-ranked search result.
    result = results[0]
    return (
        int(result["row_id"]),
        result.get("fields", {}).get("Name", item_name),
    )


async def get_xiv_price(world_or_dc, item_id):
    """Return the cheapest current Universalis listing for an item."""
    safe_world = quote(str(world_or_dc).strip(), safe="")
    url = f"https://universalis.app/api/v2/{safe_world}/{int(item_id)}"

    params = {
        "listings": 20,
        "entries": 0,
    }

    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as response:
            if response.status == 404:
                return None

            response.raise_for_status()
            data = await response.json()

    listings = data.get("listings", [])

    if not listings:
        return None

    cheapest = min(
        listings,
        key=lambda listing: listing.get("pricePerUnit", float("inf")),
    )

    return {
        "price": int(cheapest["pricePerUnit"]),
        "quantity": int(cheapest.get("quantity", 1)),
        "world": (
            cheapest.get("worldName")
            or data.get("worldName")
            or str(world_or_dc)
        ),
        "hq": bool(cheapest.get("hq", False)),
        "last_upload_time": data.get("lastUploadTime"),
    }

def add_carrot(user_id, display_name):
    data = load_carrots()
    user_id = str(user_id)

    if user_id not in data:
        data[user_id] = {
            "name": display_name,
            "carrots": 0,
        }

    data[user_id]["name"] = display_name
    data[user_id]["carrots"] += 1

    save_carrots(data)
    return data[user_id]["carrots"]


def get_carrot_count(user_id):
    data = load_carrots()
    user = data.get(str(user_id))
    if not user:
        return 0
    return int(user.get("carrots", 0))


def get_leaderboard(limit=10):
    data = load_carrots()
    sorted_users = sorted(
        data.values(),
        key=lambda user: int(user.get("carrots", 0)),
        reverse=True,
    )
    return sorted_users[:limit]


def get_next_fact():
    global FACT_QUEUE

    if not FACT_QUEUE:
        FACT_QUEUE = HORSE_FACTS.copy()
        random.shuffle(FACT_QUEUE)

    return FACT_QUEUE.pop()


def print_changelog():
    print("=" * 40)
    print(f"Horsie Bot v{VERSION}")
    print("Changelog:")
    for item in CHANGELOG:
        print(f"- {item}")
    print("=" * 40)


def format_card(card):
    value, suit = card
    return f"{value}{suit}"


def hand_value(hand):
    total = 0
    aces = 0

    for value, _ in hand:
        if value in ["J", "Q", "K"]:
            total += 10
        elif value == "A":
            total += 11
            aces += 1
        else:
            total += int(value)

    while total > 21 and aces:
        total -= 10
        aces -= 1

    return total


def draw_card():
    values = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    suits = ["♠️", "♥️", "♦️", "♣️"]
    return random.choice(values), random.choice(suits)


def format_hand(hand):
    return " ".join(format_card(card) for card in hand)


def render_horse_track(race_horses, positions):
    lines = ["🏇 **ASCII HORSE RACE**\n"]

    for index, horse in enumerate(race_horses, start=1):
        position = min(positions[horse], HORSE_RUN_TRACK_LENGTH)
        before = "─" * position
        after = "─" * max(HORSE_RUN_TRACK_LENGTH - position, 0)
        lines.append(f"**{index}. {horse}**")
        lines.append(f"`{before}🐎{after}🏁`")

    return "\n".join(lines)


def render_horserun(race_horses, positions, event_text=None):
    lines = ["🏇 ASCII HORSE RUN", ""]

    for index, horse in enumerate(race_horses, start=1):
        position = min(positions[horse], HORSE_RUN_TRACK_LENGTH)
        before = "·" * position
        after = "·" * max(HORSE_RUN_TRACK_LENGTH - position, 0)
        track = f"{before}🐎{after}🏁"
        lines.append(f"{index}. {horse}")
        lines.append(track)
        lines.append("")

    if event_text:
        lines.append(event_text)

    return "```text\n" + "\n".join(lines).strip() + "\n```"


def get_post_channels(guild):
    if guild.me is None:
        return []
    return [
        channel for channel in guild.text_channels
        if (permissions := channel.permissions_for(guild.me)).view_channel
        and permissions.send_messages and permissions.embed_links
    ]


async def post_to_guild(guild, sender):
    for channel in get_post_channels(guild):
        try:
            await sender(channel)
            return
        except discord.HTTPException as error:
            print(f"Could not post in server {guild.id}, channel {channel.id}: {error}")
    print(f"No usable posting channel in server {guild.id}.")


async def post_changelog_to_discord():
    history = ChangelogHistory(CHANGELOG_HISTORY_FILE)

    async def send_changelog(channel):
        now = datetime.now(timezone.utc).timestamp()
        entries, known = await history.select(
            guild.id, channel, bot.user.id if bot.user else None, CHANGELOG, now,
        )
        if not entries:
            return
        lines = "\n".join(f"- {item}" for item in entries)
        heading = "Changelog additions" if known else "Changelog"
        embed = discord.Embed(
            title=f"Horsie Bot v{VERSION} is online",
            description=f"**{heading}:**\n{lines}",
        )
        if channel.permissions_for(channel.guild.me).attach_files:
            embed.set_thumbnail(url="attachment://changelog_rat.gif")
            with closing(discord.File(
                ASSETS_DIR / "changelog_rat.gif",
                filename="changelog_rat.gif",
            )) as rat:
                await channel.send(embed=embed, file=rat)
        else:
            await channel.send(embed=embed)
        history.record(guild.id, known + entries, now)

    for guild in bot.guilds:
        await post_to_guild(guild, send_changelog)

async def send_horse(channel):
    image = random.choice(HORSE_IMAGES)
    caption = line("horse_caption")
    fact = get_next_fact()

    embed = discord.Embed(
        title=line("horse_title"),
        description=f"{caption}\n\n**Horse fact:** {fact}",
    )
    embed.set_image(url=image)

    await channel.send(embed=embed)


async def send_temporary_message(channel, message, delay=5):
    sent_message = await channel.send(message)
    await asyncio.sleep(delay)

    try:
        await sent_message.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        print("Missing permission to delete temporary message.")
    except discord.HTTPException as error:
        print(f"Could not delete temporary message: {error}")


async def trample_some_messages(ctx, amount):
    if amount < 1:
        await ctx.send("🐴 The horse refuses to trample zero messages.")
        return

    if amount > 100:
        await ctx.send(
            "🐴 That is too many messages for one mini-stampede. "
            "Use `!trample all` for the full herd."
        )
        return

    warning = await ctx.send(f"🐴 The herd is lining up to trample {amount} messages...")

    await asyncio.sleep(2)

    deleted = await ctx.channel.purge(limit=amount + 2)
    trampled_messages = max(len(deleted) - 2, 0)

    await send_temporary_message(
        ctx.channel,
        f"🐎💨 The herd galloped through and trampled {trampled_messages} messages into the mud.",
        delay=5,
    )


async def trample_all_messages(ctx):
    warning = await ctx.send(
        "🐴🐴🐴 The full herd has entered the pasture. "
        f"Trampling up to {TRAMPLE_ALL_MAX_MESSAGES} recent messages..."
    )

    await asyncio.sleep(2)

    total_deleted = 0
    before_message = warning

    while total_deleted < TRAMPLE_ALL_MAX_MESSAGES:
        remaining = TRAMPLE_ALL_MAX_MESSAGES - total_deleted
        batch_limit = min(100, remaining)

        deleted = await ctx.channel.purge(
            limit=batch_limit,
            before=before_message,
            bulk=True,
        )

        if not deleted:
            break

        total_deleted += len(deleted)
        before_message = deleted[-1]
        await asyncio.sleep(1)

    try:
        await warning.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        print("Missing permission to delete trample warning message.")
    except discord.HTTPException as error:
        print(f"Could not delete trample warning message: {error}")

    await send_temporary_message(
        ctx.channel,
        f"🐎💨 The herd has finished trampling. {total_deleted} messages were flattened into hoofprints.",
        delay=8,
    )


def get_forever_countdown_name():
    now = datetime.now(timezone.utc)
    remaining = WOW_FOREVER_LAUNCH - now

    if remaining.total_seconds() <= 0:
        return "wow-forever-live"

    total_minutes = max(0, int(remaining.total_seconds() // 60))
    days, remaining_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remaining_minutes, 60)

    if days > 0:
        return f"wow-forever-{days}d-{hours:02d}h"

    if hours > 0:
        return f"wow-forever-{hours:02d}h-{minutes:02d}m"

    return f"wow-forever-{minutes:02d}m"


@tasks.loop(minutes=10)
async def update_forever_countdown():
    new_name = get_forever_countdown_name()
    for guild in bot.guilds:
        channel_id = get_forever_channel_id(guild)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            channel = find_existing_forever_countdown_channel(guild)
        if channel is None:
            continue

        try:
            save_forever_config(guild.id, channel.id)
        except OSError as error:
            print(f"Could not save countdown for server {guild.id}: {error}")

        if channel.name == new_name:
            continue
        try:
            await channel.edit(name=new_name, reason="WoW Forever launch countdown")
            print(f"Forever countdown updated in server {guild.id}: {new_name}")
        except discord.HTTPException as error:
            print(f"Could not update countdown in server {guild.id}: {error}")

@update_forever_countdown.before_loop
async def before_forever_countdown():
    await bot.wait_until_ready()



@tasks.loop(minutes=5)
async def check_xiv_market():
    watches = load_xiv_watches()

    if not watches:
        return

    completed_ids = set()

    for watch in watches:
        try:
            market = await get_xiv_price(
                watch["world"],
                watch["item_id"],
            )

            if not market:
                continue

            if market["price"] <= int(watch["target_price"]):
                channel = bot.get_channel(int(watch["channel_id"]))

                if channel is None:
                    print(
                        f"Could not find Discord channel {watch['channel_id']} "
                        f"for XIV watch {watch['id']}."
                    )
                    continue

                quality = " HQ" if market["hq"] else ""

                await channel.send(
                    f"<@{watch['user_id']}> **FFXIV market alert!**\n"
                    f"**{watch['item_name']}{quality}** is now "
                    f"**{market['price']:,} gil** on **{market['world']}**.\n"
                    f"Your target was **{int(watch['target_price']):,} gil** or lower.\n"
                    f"Watch `{watch['id']}` has been completed."
                )
                completed_ids.add(str(watch["id"]))

        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, TypeError, ValueError) as error:
            print(f"FFXIV market watch {watch.get('id', 'unknown')} failed: {error}")

        # Be polite to the external API and avoid bursts when several watches exist.
        await asyncio.sleep(0.25)

    # Reload before saving so a watch added while this loop was checking prices
    # is not accidentally overwritten.
    if completed_ids:
        current_watches = load_xiv_watches()
        current_watches = [
            watch
            for watch in current_watches
            if str(watch.get("id", "")) not in completed_ids
        ]
        save_xiv_watches(current_watches)


@check_xiv_market.before_loop
async def before_xiv_market():
    await bot.wait_until_ready()

@tasks.loop(time=time(hour=9, minute=0, tzinfo=timezone.utc))
async def post_daily_horse():
    for guild in bot.guilds:
        await post_to_guild(guild, send_horse)

@post_daily_horse.before_loop
async def before_daily_loop():
    await bot.wait_until_ready()


@bot.event
async def setup_hook():
    await bot.add_cog(GameCommands(bot, find_xiv_item))
    await bot.add_cog(HorseReactions())
    await bot.add_cog(HorseArticles())
    await bot.add_cog(RealityCheck(bot))
    await bot.add_cog(HorseChat(bot))


@bot.event
async def on_ready():
    global startup_announced
    print(f"Logged in as {bot.user}")
    if not startup_announced:
        startup_announced = True
        print_changelog()
        await post_changelog_to_discord()

    if not post_daily_horse.is_running():
        post_daily_horse.start()

    if not update_forever_countdown.is_running():
        update_forever_countdown.start()

    if not check_xiv_market.is_running():
        check_xiv_market.start()


@bot.command()
async def horse(ctx):
    await send_horse(ctx.channel)


@bot.command()
async def horsefact(ctx):
    await ctx.send(f"{line('fact_intro')}: {get_next_fact()}")


@bot.command()
async def carrots(ctx, member: discord.Member = None):
    member = member or ctx.author
    count = get_carrot_count(member.id)

    if member.id == ctx.author.id:
        await ctx.send(line("carrots_self", count=count))
    else:
        await ctx.send(line("carrots_other", name=discord.utils.escape_markdown(member.display_name), count=count))


@bot.command()
async def leaderboard(ctx):
    leaders = get_leaderboard()

    if not leaders:
        await ctx.send(line("empty_leaderboard"))
        return

    lines = []
    for index, user in enumerate(leaders, start=1):
        name = user.get("name", "Unknown Horse")
        carrots = int(user.get("carrots", 0))
        lines.append(f"**{index}.** {name} — 🥕 **{carrots}**")

    await ctx.send("🏆 **Stable Carrot Leaderboard**\n\n" + "\n".join(lines))



@bot.command()
async def xivprice(ctx, world: str, *, item: str):
    """Show the cheapest current Universalis listing for an FFXIV item."""
    try:
        async with ctx.typing():
            found = await find_xiv_item(item)

            if not found:
                await ctx.send(f"Could not find FFXIV item: **{item}**")
                return

            item_id, item_name = found
            market = await get_xiv_price(world, item_id)

    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        print(f"!xivprice API error: {error}")
        await ctx.send("The FFXIV market APIs are not responding right now. Try again shortly.")
        return

    if not market:
        await ctx.send(
            f"No current market listings found for **{item_name}** on **{world}**."
        )
        return

    quality = " HQ" if market["hq"] else ""

    await ctx.send(
        f"**{item_name}{quality}**\n"
        f"Cheapest: **{market['price']:,} gil each**\n"
        f"World: **{market['world']}**\n"
        f"Quantity: **{market['quantity']}**"
    )


@bot.command()
@commands.guild_only()
async def xivwatch(ctx, world: str, max_price: str, *, item: str):
    """Create a one-shot FFXIV market alert."""
    try:
        target_price = int(
            max_price.replace(",", "").replace(".", "").replace("_", "")
        )
    except ValueError:
        await ctx.send(
            "Price must be a whole number. "
            "Example: `!xivwatch Light 500000 Dark Matter`"
        )
        return

    if target_price <= 0:
        await ctx.send("The target price must be greater than 0 gil.")
        return

    try:
        async with ctx.typing():
            found = await find_xiv_item(item)

            if not found:
                await ctx.send(f"Could not find FFXIV item: **{item}**")
                return

            item_id, item_name = found
            market = await get_xiv_price(world, item_id)

    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        print(f"!xivwatch API error: {error}")
        await ctx.send("The FFXIV market APIs are not responding right now. Try again shortly.")
        return

    if not market:
        await ctx.send(
            f"No current market listings found for **{item_name}** on **{world}**."
        )
        return

    if market["price"] <= target_price:
        quality = " HQ" if market["hq"] else ""
        await ctx.send(
            f"{ctx.author.mention} **{item_name}{quality}** is already "
            f"**{market['price']:,} gil** on **{market['world']}**."
        )
        return

    watches = load_xiv_watches()
    watch_id = uuid.uuid4().hex[:6]

    watches.append(
        {
            "id": watch_id,
            "guild_id": ctx.guild.id,
            "channel_id": ctx.channel.id,
            "user_id": ctx.author.id,
            "world": world,
            "item_id": item_id,
            "item_name": item_name,
            "target_price": target_price,
        }
    )

    try:
        save_xiv_watches(watches)
    except OSError as error:
        print(f"Could not save XIV watch: {error}")
        await ctx.send("I found the item, but could not save the market watch.")
        return

    await ctx.send(
        f"Watching **{item_name}** on **{world}**.\n"
        f"Current cheapest: **{market['price']:,} gil**\n"
        f"Alert at: **{target_price:,} gil** or lower\n"
        f"Watch ID: `{watch_id}`"
    )


@bot.command()
async def xivwatches(ctx):
    """List the caller's active FFXIV market alerts."""
    watches = [
        watch
        for watch in load_xiv_watches()
        if int(watch.get("user_id", 0)) == ctx.author.id
    ]

    if not watches:
        await ctx.send("You have no active FFXIV market watches.")
        return

    lines = []

    for watch in watches:
        lines.append(
            f"`{watch['id']}` — **{watch['item_name']}** "
            f"on **{watch['world']}** <= "
            f"**{int(watch['target_price']):,} gil**"
        )

    message = "**Your FFXIV market watches**\n" + "\n".join(lines)
    await ctx.send(message[:2000])


@bot.command()
async def xivunwatch(ctx, watch_id: str):
    """Remove one of the caller's FFXIV market alerts."""
    watches = load_xiv_watches()

    new_watches = [
        watch
        for watch in watches
        if not (
            str(watch.get("id", "")).casefold() == watch_id.casefold()
            and int(watch.get("user_id", 0)) == ctx.author.id
        )
    ]

    if len(new_watches) == len(watches):
        await ctx.send("I could not find one of your watches with that ID.")
        return

    try:
        save_xiv_watches(new_watches)
    except OSError as error:
        print(f"Could not remove XIV watch: {error}")
        await ctx.send("I found that watch, but could not update the watch file.")
        return

    await ctx.send(f"Removed FFXIV market watch `{watch_id}`.")

@bot.command()
@commands.max_concurrency(1, per=commands.BucketType.channel, wait=False)
async def horserace(ctx):
    if len(HORSE_RACE_NAMES) < 4:
        await ctx.send("🐴 Not enough horses are registered for the race.")
        return

    race_horses = random.sample(HORSE_RACE_NAMES, 4)
    bets = await collect_race_bets(bot, ctx, race_horses)

    await ctx.send(line("bets_closed"))

    await asyncio.sleep(2)
    await ctx.send("3...")
    await asyncio.sleep(1)
    await ctx.send("2...")
    await asyncio.sleep(1)
    await ctx.send("1...")
    await asyncio.sleep(1)
    await ctx.send(random.choice(HORSE_RACE_STARTS))

    positions = {horse: 0 for horse in race_horses}
    round_number = 1
    winner = None
    event_log = ["🎙️ The horses are lined up. The carrots are nervous."]

    await asyncio.sleep(1)

    race_board = await ctx.send(
        f"{render_horse_track(race_horses, positions)}\n\n"
        "**Race Commentary**\n"
        + "\n".join(event_log)
    )

    while winner is None:
        await asyncio.sleep(2)

        for horse in race_horses:
            positions[horse] += random.randint(1, 3)

        # Most rounds get a silly event. Events can boost or slow one horse.
        if random.random() < 0.85:
            event_template, movement = random.choice(HORSE_RUN_EVENTS)
            event_horse = random.choice(race_horses)
            positions[event_horse] = max(0, positions[event_horse] + movement)
            event_text = event_template.format(horse=f"**{event_horse}**")
        else:
            event_template = random.choice(HORSE_RACE_EVENTS)
            event_horse = random.choice(race_horses)
            event_text = event_template.format(horse=f"**{event_horse}**")

        event_log.append(f"**Round {round_number}:** {event_text}")

        for horse in race_horses:
            if positions[horse] >= HORSE_RUN_TRACK_LENGTH:
                winner = horse
                break

        # Discord messages have a 2000 character limit.
        # Keep the latest commentary lines if the race gets unusually wordy.
        visible_event_log = event_log[-10:]

        race_message = (
            f"**Round {round_number}**\n"
            f"{render_horse_track(race_horses, positions)}\n\n"
            "**Race Commentary**\n"
            + "\n".join(visible_event_log)
        )

        try:
            await race_board.edit(content=race_message)
        except discord.NotFound:
            # If the board was deleted, create a new one and continue.
            race_board = await ctx.send(race_message)
        except discord.HTTPException:
            # If Discord refuses the edit for some reason, fall back to one new message.
            race_board = await ctx.send(race_message)

        round_number += 1

        # Safety fallback so the race never drags forever.
        if round_number > 12 and winner is None:
            winner = max(race_horses, key=lambda horse: positions[horse])

    await asyncio.sleep(1)

    winning_number = race_horses.index(winner) + 1
    winning_horse = winner

    final_event = random.choice(HORSE_RACE_FINAL_EVENTS)
    event_log.append(f"🏁 **Finish:** {final_event}")

    visible_event_log = event_log[-10:]

    final_board_message = (
        "**Final Round**\n"
        f"{render_horse_track(race_horses, positions)}\n\n"
        "**Race Commentary**\n"
        + "\n".join(visible_event_log)
    )

    try:
        await race_board.edit(content=final_board_message)
    except discord.NotFound:
        race_board = await ctx.send(final_board_message)
    except discord.HTTPException:
        race_board = await ctx.send(final_board_message)

    winning_bets = [
        bet
        for bet in bets.values()
        if bet["choice"] == winning_number
    ]

    dramatic_finish = random.choice(
        [
            "wins by a nose!",
            "wins after a deeply suspicious burst of speed!",
            "wins while looking like this was the plan all along!",
            "wins and immediately demands a snack-based contract renegotiation!",
            "wins so dramatically that the grass applauds!",
            "wins despite spending most of the race emotionally elsewhere!",
            "wins after discovering the ancient art of going slightly faster!",
            "wins with the confidence of a horse that has never paid rent!",
        ]
    )

    if winning_bets:
        winners = []
        for bet in winning_bets:
            new_total = add_carrot(bet["user_id"], bet["name"])
            name = discord.utils.escape_markdown(bet["name"])
            winners.append(f"{name} (+1 carrot, now {new_total})")

        await ctx.send(
            f"🏆 **#{winning_number} {winning_horse}** {dramatic_finish}\n\n"
            "🥕 The winners receive 1 carrot and eternal pasture bragging rights."
        )
        for page in winner_pages(winners):
            await ctx.send(
                f"**Correct bets:**\n{page}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
    else:
        await ctx.send(
            f"🏆 **#{winning_number} {winning_horse}** {dramatic_finish}\n\n"
            "Nobody bet on the winner.\n\n"
            f"{line('race_no_winners')}"
        )


@horserace.error
async def horserace_error(ctx, error):
    if isinstance(error, commands.MaxConcurrencyReached):
        await ctx.send("🏇 A race is already running in this channel. Wait until it finishes before starting another.")
    else:
        raise error


@bot.command()
async def horsejack(ctx):
    player_hand = [draw_card(), draw_card()]
    dealer_hand = [draw_card(), draw_card()]

    await ctx.send(
        "🃏🐴 **Horsejack!**\n\n"
        f"{line('horsejack_intro')}\n\n"
        "Try to get closer to **21** than the dealer horse.\n"
        "Type `hit` to draw another card or `stand` to stop.\n"
        "Win to earn 🥕 **1 carrot**."
    )

    while True:
        player_total = hand_value(player_hand)
        dealer_visible = dealer_hand[0]

        await ctx.send(
            f"Your hand: **{format_hand(player_hand)}** = **{player_total}**\n"
            f"Dealer horse shows: **{format_card(dealer_visible)}**\n\n"
            "Type `hit` or `stand`."
        )

        if player_total > 21:
            await ctx.send(
                f"{line('horsejack_bust')}\n"
                "No carrot this time."
            )
            return

        def check(message):
            return (
                message.channel == ctx.channel
                and message.author == ctx.author
                and message.content.lower().strip() in ["hit", "stand"]
            )

        try:
            message = await bot.wait_for("message", timeout=30, check=check)
        except asyncio.TimeoutError:
            await ctx.send(line("horsejack_timeout"))
            return

        choice = message.content.lower().strip()

        if choice == "hit":
            player_hand.append(draw_card())
            await ctx.send(line("horsejack_hit"))
        else:
            break

    await ctx.send(f"🐴 {random.choice(HORSEJACK_DEALER_REACTIONS)}")

    while hand_value(dealer_hand) < 17:
        await asyncio.sleep(1)
        dealer_hand.append(draw_card())
        await ctx.send(
            f"Dealer horse draws: **{format_hand(dealer_hand)}** = **{hand_value(dealer_hand)}**"
        )

    player_total = hand_value(player_hand)
    dealer_total = hand_value(dealer_hand)

    await asyncio.sleep(1)
    await ctx.send(
        f"Final hands:\n"
        f"You: **{format_hand(player_hand)}** = **{player_total}**\n"
        f"Dealer horse: **{format_hand(dealer_hand)}** = **{dealer_total}**"
    )

    if dealer_total > 21:
        new_total = add_carrot(ctx.author.id, ctx.author.display_name)
        await ctx.send(
            f"{line('horsejack_dealer_bust')}\n"
            f"You now have **{new_total}** carrot(s)."
        )
    elif player_total > dealer_total:
        new_total = add_carrot(ctx.author.id, ctx.author.display_name)
        await ctx.send(
            f"{line('horsejack_win')}\n"
            f"You now have **{new_total}** carrot(s)."
        )
    elif player_total == dealer_total:
        await ctx.send(line("horsejack_tie"))
    else:
        await ctx.send(line("horsejack_loss"))


@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def forevercd(ctx):
    await ctx.send(
        "🐴 Which **text channel** should I turn into the WoW Forever countdown?\n"
        "Mention it like `#general`, or type its exact name like `general`.\n"
        "You have **30 seconds**."
    )

    def check(message):
        return message.author == ctx.author and message.channel == ctx.channel

    try:
        message = await bot.wait_for(
            "message",
            timeout=30,
            check=check,
        )
    except asyncio.TimeoutError:
        await ctx.send("🐴 No channel selected. Forever countdown cancelled.")
        return

    if message.channel_mentions:
        target_channel = message.channel_mentions[0]
    else:
        requested_name = message.content.strip().lstrip("#")
        target_channel = discord.utils.get(ctx.guild.text_channels, name=requested_name)

    if target_channel is None:
        await ctx.send(
            "🐴 I could not find that text channel. Run `!forevercd` and try again."
        )
        return

    if not isinstance(target_channel, discord.TextChannel):
        await ctx.send("🐴 That is not a normal text channel. Try `!forevercd` again.")
        return

    try:
        new_name = get_forever_countdown_name()
        await target_channel.edit(
            name=new_name,
            reason=f"WoW Forever countdown configured by {ctx.author}",
        )
    except discord.Forbidden:
        await ctx.send(
            "🐴 I cannot rename that channel. Give my role **Manage Channels** permission."
        )
        return
    except discord.HTTPException as error:
        await ctx.send(f"🐴 Discord refused the channel rename: `{error}`")
        return

    try:
        save_forever_config(ctx.guild.id, target_channel.id)
    except OSError as error:
        await ctx.send(
            f"🐴 I renamed the channel, but could not save the countdown config: `{error}`"
        )
        return

    if not update_forever_countdown.is_running():
        update_forever_countdown.start()

    await ctx.send(
        f"🐴 Countdown enabled on {target_channel.mention}.\n"
        "I will keep renaming it automatically until WoW Forever launches."
    )


@forevercd.error
async def forevercd_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(
            "🐴 You need **Manage Channels** permission to configure the countdown."
        )
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send(
            "🐴 I need **Manage Channels** permission before I can rename a channel."
        )
    else:
        await ctx.send("🐴 Something went wrong while configuring the countdown.")
        raise error


@bot.command()
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def trample(ctx, amount="10"):
    amount_text = str(amount).lower().strip()

    if amount_text == "all":
        await trample_all_messages(ctx)
        return

    try:
        amount_number = int(amount_text)
    except ValueError:
        await ctx.send(
            "🐴 Tell the horse how many messages to trample. "
            "Example: `!trample 20` or `!trample all`"
        )
        return

    await trample_some_messages(ctx, amount_number)


@trample.error
async def trample_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🐴 You need **Manage Messages** permission before you can command the herd.")
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send("🐴 This horse needs **Manage Messages** permission before it can trample anything.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("🐴 Use `!trample 20` or `!trample all`.")
    elif isinstance(error, discord.Forbidden):
        await ctx.send("🐴 Discord blocked the stampede. Check the bot role permissions and role order.")
    elif isinstance(error, discord.HTTPException):
        await ctx.send(
            "🐴 The herd stumbled over Discord's message deletion limits. "
            "Some older messages may not be removable."
        )
    else:
        await ctx.send("🐴 The horse got confused and trampled the command incorrectly.")
        raise error


def main():
    if not TOKEN:
        raise RuntimeError("Missing DISCORD_BOT_TOKEN")

    run_bot(bot, TOKEN)


if __name__ == "__main__":
    main()
