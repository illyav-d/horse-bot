import os
import random
import asyncio
import json
import re
from pathlib import Path
import discord
from discord.ext import commands, tasks
from datetime import datetime, time, timezone

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))

# Safety cap for !trample all.
# You can change this in your environment variables if needed.
TRAMPLE_ALL_MAX_MESSAGES = int(os.getenv("TRAMPLE_ALL_MAX_MESSAGES", "1000"))

# Local save file for carrot points.
# This keeps scores even after the bot restarts.
CARROT_FILE = Path(os.getenv("CARROT_FILE", "carrots.json"))

# Local save file for the WoW Forever countdown channel.
# This lets the countdown resume automatically after a bot restart.
FOREVER_CONFIG_FILE = Path(os.getenv("FOREVER_CONFIG_FILE", "forever_countdown.json"))

# WoW Forever launch: 5 November 2026 at 00:00 Belgian time (CET).
# Stored as UTC to keep the countdown timezone-safe.
WOW_FOREVER_LAUNCH = datetime(2026, 11, 4, 23, 0, 0, tzinfo=timezone.utc)

FOREVER_CHANNEL_PATTERN = re.compile(
    r"^wow-forever-(?:\d+d-\d{2}h|\d{2}h-\d{2}m|\d{2}m|live)$",
    re.IGNORECASE,
)

VERSION = "1.6.4"

CHANGELOG = [
    "Upgraded !horserace into a visual ASCII horse race.",
    "Players can now pick a horse and watch the race move across the track.",
    "The race board edits one message instead of reposting the ASCII art every round.",
    "Race narration now builds up as a visible event log under the track.",
    "Added random ASCII race events like carrot boosts, bucket delays, and suspicious speed.",
    "Correct guesses in !horserace still earn 1 carrot.",
    "The stable now has cleaner live sports coverage with actual commentary, technically.",
    "Added !forevercd to turn a selected text channel into a persistent WoW Forever launch countdown.",
    "WoW Forever countdown channels are now auto-detected after bot restarts, even if the saved config is missing.",
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

HORSE_CAPTIONS = [
    'Daily horse delivery.',
    'Horse of the day.',
    'A horse has arrived.',
    'Neigh.',
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
    'Horses have larger eyes by volume than any other land-dwelling mammal on earth.',
    'Male horses are among the very few male mammals that do not possess nipples.',
    "A horse's brain weighs only about 22 ounces, which is roughly half the weight of a human brain.",
    'Horses are obligate nasal breathers, meaning they can only breathe through their noses and cannot use their mouths to inhale air.',
    'Because of a tight, one-way valve in their esophagus, it is physically impossible for a horse to burp or vomit.',
    'Horses do not produce saliva automatically and must chew to generate it, producing up to 11 gallons daily.',
    'Just like humans, equines with pale pink skin can easily get a painful sunburn.',
    "Foals are born with a soft, rubbery layer over their hooves to protect the mother's birth canal from injury.",
    "An adult horse's heart weighs between 8.5 and 10 pounds, roughly matching the size of a basketball.",
    'Horses can read human facial expressions and remember your past emotional state.',
    'Certain heavily feathered draft breeds, like the Gypsy Vanner, are genetically capable of growing full mustaches.',
    'When horses curl up their upper lip to look like they are laughing, they are actually gathering scents.',
    "A horse's ears point where its eyes look; pointing in two directions means it is looking at two things at once.",
    'To stay safe from predators, a herd will never sleep lying down all at the same time.',
    "Studies show that pumping lavender-scented air into a stable significantly lowers a horse's elevated heart rate.",
    'The earliest ancestor of the horse was the Eohippus, a small jungle creature the size of a Golden Retriever.',
    'Over millions of years of evolution, horses shifted from walking on multiple toes to standing entirely on a single central digit.',
    'The longest-living horse on official record was named Old Billy, who survived to the remarkable age of 62.',
    'The Przewalski’s horse is the only true wild horse species left, as all other wild herds are actually feral.',
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


def load_carrots():
    if not CARROT_FILE.exists():
        return {}

    try:
        with CARROT_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        print("carrots.json was invalid. Starting with an empty carrot tracker.")
        return {}


def save_carrots(data):
    with CARROT_FILE.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


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


def save_forever_config(channel_id):
    data = {"channel_id": int(channel_id)}

    with FOREVER_CONFIG_FILE.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


def get_forever_channel_id():
    data = load_forever_config()

    try:
        return int(data.get("channel_id", 0))
    except (TypeError, ValueError):
        return 0


def find_existing_forever_countdown_channel():
    """Find an existing WoW Forever countdown channel by its generated name."""
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if FOREVER_CHANNEL_PATTERN.fullmatch(channel.name):
                return channel

    return None


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


async def post_changelog_to_discord():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"Could not find channel {CHANNEL_ID} for changelog post")
        return

    lines = "\n".join(f"- {item}" for item in CHANGELOG)
    await channel.send(
        f"**Horsie Bot v{VERSION} is online**\n"
        f"**Changelog:**\n{lines}"
    )


async def send_horse(channel):
    image = random.choice(HORSE_IMAGES)
    caption = random.choice(HORSE_CAPTIONS)
    fact = get_next_fact()

    embed = discord.Embed(
        title="Horse of the Day",
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
    channel_id = get_forever_channel_id()
    channel = bot.get_channel(channel_id) if channel_id else None

    # Recovery path for restarts, fresh deployments, or a missing/stale config file.
    # The generated countdown channel name becomes the fallback source of truth.
    if channel is None:
        channel = find_existing_forever_countdown_channel()

        if channel is None:
            if channel_id:
                print(
                    f"Forever countdown channel {channel_id} could not be found, "
                    "and no wow-forever countdown channel was detected."
                )
            return

        print(
            f"Recovered WoW Forever countdown channel from its name: "
            f"{channel.name} ({channel.id})"
        )

        try:
            save_forever_config(channel.id)
        except OSError as error:
            # Recovery still works for this process even if the config cannot be written.
            print(f"Could not save recovered Forever countdown config: {error}")

    if not isinstance(channel, discord.TextChannel):
        print(f"Forever countdown channel {channel.id} is not a text channel.")
        return

    new_name = get_forever_countdown_name()

    # Avoid unnecessary API calls when the visible countdown has not changed.
    if channel.name == new_name:
        return

    try:
        await channel.edit(
            name=new_name,
            reason="WoW Forever launch countdown",
        )
        print(f"Forever countdown updated: {new_name}")
    except discord.Forbidden:
        print(
            f"Missing Manage Channels permission for countdown channel {channel.id}."
        )
    except discord.HTTPException as error:
        print(f"Could not update countdown channel {channel.id}: {error}")


@update_forever_countdown.before_loop
async def before_forever_countdown():
    await bot.wait_until_ready()


@tasks.loop(time=time(hour=9, minute=0, tzinfo=timezone.utc))
async def post_daily_horse():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"Could not find channel {CHANNEL_ID}")
        return

    await send_horse(channel)


@post_daily_horse.before_loop
async def before_daily_loop():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print_changelog()
    await post_changelog_to_discord()

    if not post_daily_horse.is_running():
        post_daily_horse.start()

    if not update_forever_countdown.is_running():
        update_forever_countdown.start()


@bot.command()
async def horse(ctx):
    await send_horse(ctx.channel)


@bot.command()
async def horsefact(ctx):
    await ctx.send(f"Horse fact: {get_next_fact()}")


@bot.command()
async def carrots(ctx, member: discord.Member = None):
    member = member or ctx.author
    count = get_carrot_count(member.id)

    if member.id == ctx.author.id:
        await ctx.send(f"🥕 You have **{count}** carrot(s).")
    else:
        await ctx.send(f"🥕 **{member.display_name}** has **{count}** carrot(s).")


@bot.command()
async def leaderboard(ctx):
    leaders = get_leaderboard()

    if not leaders:
        await ctx.send("🥕 The carrot leaderboard is empty. Win a game to earn the first carrot!")
        return

    lines = []
    for index, user in enumerate(leaders, start=1):
        name = user.get("name", "Unknown Horse")
        carrots = int(user.get("carrots", 0))
        lines.append(f"**{index}.** {name} — 🥕 **{carrots}**")

    await ctx.send("🏆 **Stable Carrot Leaderboard**\n\n" + "\n".join(lines))


@bot.command()
async def horserace(ctx):
    if len(HORSE_RACE_NAMES) < 4:
        await ctx.send("🐴 Not enough horses are registered for the race.")
        return

    race_horses = random.sample(HORSE_RACE_NAMES, 4)
    bets = {}

    horse_list = "\n".join(
        f"{index + 1}. **{name}**"
        for index, name in enumerate(race_horses)
    )

    await ctx.send(
        "🏇 **Horse Race!**\n\n"
        "Pick your horse by typing a number from **1** to **4**.\n"
        "This race has a tiny ASCII track and terrible sports journalism.\n"
        "Correct guesses earn 🥕 **1 carrot**.\n\n"
        f"{horse_list}\n\n"
        "You have **20 seconds** to place your bets!"
    )

    def bet_check(message):
        return (
            message.channel == ctx.channel
            and not message.author.bot
            and message.content.strip() in ["1", "2", "3", "4"]
        )

    end_time = asyncio.get_event_loop().time() + 20

    while asyncio.get_event_loop().time() < end_time:
        timeout = max(0.1, min(2, end_time - asyncio.get_event_loop().time()))

        try:
            message = await bot.wait_for("message", timeout=timeout, check=bet_check)
        except asyncio.TimeoutError:
            continue

        choice = int(message.content.strip())
        bets[message.author.id] = {
            "user_id": message.author.id,
            "name": message.author.display_name,
            "choice": choice,
        }

        chosen_horse = race_horses[choice - 1]

        try:
            await message.add_reaction("🏇")
        except discord.HTTPException:
            pass

        await ctx.send(f"🎟️ **{message.author.display_name}** bets on **#{choice} {chosen_horse}**!")

    await ctx.send("🔔 Bets are closed! The horses are being gently convinced to face the correct direction...")

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
            winners.append(f"{bet['name']} (+1 carrot, now {new_total})")

        winners_text = ", ".join(winners)

        await ctx.send(
            f"🏆 **#{winning_number} {winning_horse}** {dramatic_finish}\n\n"
            f"Correct bets: **{winners_text}**\n\n"
            "🥕 The winners receive 1 carrot and eternal pasture bragging rights."
        )
    else:
        await ctx.send(
            f"🏆 **#{winning_number} {winning_horse}** {dramatic_finish}\n\n"
            "Nobody bet on the winner.\n\n"
            "🐴 The horse celebrates alone, which is honestly very powerful."
        )


@bot.command()
async def horsejack(ctx):
    player_hand = [draw_card(), draw_card()]
    dealer_hand = [draw_card(), draw_card()]

    await ctx.send(
        "🃏🐴 **Horsejack!**\n\n"
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
                "💥 You busted! The dealer horse slowly eats your paperwork.\n"
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
            await ctx.send("⌛ You waited too long. The dealer horse got bored and wandered away.")
            return

        choice = message.content.lower().strip()

        if choice == "hit":
            player_hand.append(draw_card())
            await ctx.send("🃏 You draw another card. The horse squints judgmentally.")
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
            f"🏆 Dealer horse busted! You win 🥕 **1 carrot**.\n"
            f"You now have **{new_total}** carrot(s)."
        )
    elif player_total > dealer_total:
        new_total = add_carrot(ctx.author.id, ctx.author.display_name)
        await ctx.send(
            f"🏆 You beat the dealer horse and win 🥕 **1 carrot**.\n"
            f"You now have **{new_total}** carrot(s)."
        )
    elif player_total == dealer_total:
        await ctx.send("🤝 Push! You tied with the dealer horse. No carrot, but your honor survives.")
    else:
        await ctx.send("🐴 Dealer horse wins. It looks far too smug. No carrot this time.")


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
        save_forever_config(target_channel.id)
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


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Missing DISCORD_BOT_TOKEN")
    if CHANNEL_ID == 0:
        raise RuntimeError("Missing DISCORD_CHANNEL_ID")

    bot.run(TOKEN)
