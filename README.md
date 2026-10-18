# Horsie Bot 🐴

A small Discord bot with horse-themed commands, games, a WoW Forever countdown, and an FFXIV market-board watcher.

Current version: **1.8.5**

## Project Layout

- `horsie/`: bot code and Discord features.
- `tests/`: offline tests.
- `assets/`: images, GIFs, and videos.
- `data/`: local saves and login cooldown state, excluded from Git.
- `docs/`: supporting documentation and horse fact sources.
- `scripts/`: local PowerShell launcher with your private configuration.

Run `python main.py` or `python -m horsie` from the project folder. The existing `./StartHorseBot.ps1` shortcut and `StartHorsie.bat` still work. Local saves and bundled assets resolve from the project directory even when the launcher is called from another folder. Railway continues using its attached volume for saves.

Older local saves in the project root remain readable until moved into `data/`. Stop the bot before moving save files so a running process cannot write to the old location.

## Discord Login Backoff

Discord login rate limits now wait in-process instead of triggering Railway restart loops. HTTP 429 login failures use a 15-minute cooldown, doubling up to an hour, and respect longer server retry headers. The cooldown is saved on the Railway volume and survives restarts. Invalid tokens stop login attempts until an operator updates the token and restarts the service. Reconnecting does not repost the startup changelog. These safeguards cannot remove an existing Cloudflare restriction or establish its original cause.

## Features

- Daily horse post
- Horse facts
- Carrot points and leaderboard
- ASCII horse racing
- Horsejack
- Message trampling
- WoW Forever countdown channel
- FFXIV market-board price checks
- FFXIV price alerts that run continuously while the bot is hosted
- WoW retail character cards
- FFXIV NQ/HQ price trends from recent sales
- A kitchen horse photo whenever someone says "macaroni horse"
- Varied horse posts, facts, carrot replies, race announcements, and Horsejack text
- On-demand light horse articles
- Mention Horsie and ask "is this real?" to assess the latest image for signs of AI generation

## Version 1.8.5

- `!horsearticle` opens live article pages and searches archives beyond the current feeds, including Horse Nation. It shows **Searching...** while it reads and keeps filtering for light stories without repeats.
- Carrot balances and article history use the attached Railway volume, so updates preserve progress. Old carrot snapshots are no longer shipped in Git, and saves are written atomically.
- Added a standard Python entry point so hosting platforms can detect how to start Horsie.

## Version 1.8.4

- Horsie read a book. More horse facts.
- Added 30 facts about whiskers, colours, movement, ponies, and horse behaviour. Tidied up a few duplicate or questionable older claims.
- New fact references are listed in [HORSE_FACT_SOURCES.md](docs/HORSE_FACT_SOURCES.md). Facts appear in both `!horsefact` and horse posts through the existing shuffled rotation.

## Version 1.8.3

- `!horsearticle` finds a happy horse story. If you've seen one already, Horsie digs up another.

## Version 1.8.2

- Say `macaroni horse`. You know what happens.
- Gave Horsie a few more things to say. He was repeating himself.

## Version 1.8.1

- One race at a time per channel now. Four horses were enough chaos.
- Fixed picks getting missed when everyone answered at once. You can change your pick until bets close.
- `!wow` checks retail characters. `!xivtrend` checks FFXIV prices. Classic cards and raid recaps can wait.

## Version 1.7.1

- Daily horses, changelogs and the Forever countdown now work across servers. Horsie has discovered sharing.

## Commands

| Command | Description |
|---|---|
| `!horse` | Posts a random horse |
| `!horsefact` | Posts a random horse fact |
| `!carrots` | Shows your carrot balance |
| `!carrots @user` | Shows another user's carrot balance |
| `!leaderboard` | Shows the carrot leaderboard |
| `!horserace` | Starts an interactive horse race |
| `!horsejack` | Starts Horsejack |
| `!forevercd` | Configures a WoW Forever countdown channel |
| `!trample 20` | Deletes recent messages |
| `!trample all` | Deletes messages up to the configured safety limit |
| `!xivprice <world/DC> <item>` | Gets the cheapest current FFXIV market listing |
| `!xivwatch <world/DC> <price> <item>` | Creates an FFXIV price alert |
| `!xivwatches` | Lists your active FFXIV price alerts |
| `!xivunwatch <id>` | Removes an FFXIV price alert |
| `!wow <region> <realm> <character>` | Retail WoW character card via Raider.IO |
| `!xivtrend <world/DC> <item> [--hq or --nq]` | Compares recent sale prices and current listings; defaults to NQ |
| `macaroni horse` (no prefix) | Posts the kitchen horse photo |
| `!horsearticle` | Finds the latest suitable light horse story |
| `@Horsie is this real?` | Assesses the latest image in this channel for possible AI generation |

## Image Reality Checks

Post or link an image or GIF, then mention the bot and ask `@Horsie is this real?` (select the actual bot mention in Discord). `is it real?`, `is that AI?`, and `real or AI?` also work with a mention. Horsie scans the last 50 messages in that channel and checks the most recent message containing a supported image, skipping intervening chat. An image attached to the question takes priority; replying to a specific image message selects that message instead. The answer links the checked message.

An admin must set `GEMINI_API_KEY` on the host (Railway service > Variables). Create a key in [Google AI Studio](https://aistudio.google.com/apikey). `REALITY_CHECK_MODEL` optionally overrides the default `gemini-3.8-flash`; use a Gemini model supporting images, structured outputs and low thinking effort. Remove any old OpenAI or Gemini 2.5 model override. Google rejects Gemini 2.5 Flash for new accounts; the default is Gemini 3.8 Flash. The selected images are downloaded and sent to Google Gemini for analysis. Gemini 3.8 Flash offers a [free tier with usage limits](https://ai.google.dev/gemini-api/docs/pricing); keep the Google project on the free tier to avoid paid usage. When the quota is reached, Horsie asks you to try later. Temporary server failures (including HTTP 503) and connection failures are retried up to twice, with short exponential delays and jitter. API attempts share a 40-second deadline inside the existing 55-second overall check limit. Invalid keys, access errors, model errors and quota errors are not retried. Google's free-tier data terms apply. No API key is stored in the repository. This uses the [Gemini image input API](https://ai.google.dev/gemini-api/docs/generate-content/image-understanding).

Horsie gives a short **Likely AI-generated**, **Likely authentic**, or **Inconclusive** assessment with reasons and a reminder that it is not proof of origin. It does not verify factual claims, search for originals or authenticate provenance. JPG, PNG, WebP and GIF uploads, direct HTTPS image links, and images exposed by link previews are supported, with up to three images per message, an 8 MB limit per image and a 12 MB combined image limit. Downloads require public HTTPS URLs, validate redirects and file signatures, and enforce size limits while streaming. For GIFs, Horsie samples up to four frames spread across the animation and labels the result as based on sampled frames. It supports uploaded GIFs, direct GIF URLs, and Tenor/Giphy GIF previews exposed by Discord. GIF decoding runs off the Discord event loop, with limits of 200 frames, 16 million pixels per frame, and 100 million total frame pixels; larger animations need a shorter GIF or screenshot. Videos and links without a readable image need a screenshot or direct image/GIF upload. Only the selected images are analyzed; surrounding chat and image captions are not submitted. Each person can request one check every 30 seconds, with one check per channel and three across the bot at a time. The bot needs Read Message History and permission to send replies. Without an API key, this feature explains that it is not connected; other features continue working.

## Horse Articles

Run `!horsearticle` in a server channel where Horsie can reply. Horsie immediately posts **Searching...**, then replaces that message with the result. Each request checks current [Horse & Hound](https://www.horseandhound.co.uk/) and [Horse Nation](https://www.horsenation.com/) stories online, opens the actual article pages, and searches their archives when the current feed entries have been read or are unsuitable. It can find photo challenges, comics, videos, and other light horse stories beyond the RSS window. No API key or automatic posting is required.

The bot checks article text for death, injury, abuse, and other heavy topics before sharing a link, and keeps the past-year date filter. It skips paywalled pages and pages without enough readable article text. Navigation, adverts, and unrelated sidebar stories are excluded from the text check. Searches last at most 55 seconds, examine at most 24 article pages, and can walk up to 12 archive pages per site. Slow or unavailable pages are skipped; a timeout replaces the searching message with a retry message.

Each server keeps its own list of shared article links in `horse_articles.json` (set `HORSE_ARTICLE_FILE` to change the location). Links are only recorded after the result is successfully shown, and older history is retained to avoid repeats. If nothing unread passes the checks within the search limits, Horsie says so. The filters are intentionally conservative; they can miss a nice article, and automated screening cannot guarantee every linked page will be free of upsetting material.

## Macaroni Horse

Say `macaroni horse` in chat; for example, `MACARONI HORSE!` or `someone summon macaroni horse`. Horsie posts the photo in the same channel with a random caption. The image is bundled at `assets/macaroni_horse.jpg`, so deployment does not depend on your Downloads folder. Include that asset when committing/deploying. The bot needs **Attach Files** as well as permission to view and send messages in that channel.

## Horse Races

Use `!horserace` to start a race. Only one race can run in a channel at a time, including the betting window and result announcements. Other channels can run their own races.

Send `1`, `2`, `3`, or `4` during the 20-second betting window. Picks from multiple players are recorded independently of Discord sends and edits. Your latest valid number replaces your earlier pick; each player receives at most one reward. Bots, other channels, invalid numbers, and picks after the deadline are ignored.

One betting board shows the number of picks for each horse and refreshes every two seconds when picks change. Per-pick reactions and confirmation messages have been removed to reduce Discord traffic.

## WoW Character Cards

```text
!wow eu silvermoon CharacterName
!wow eu "Realm Name" CharacterName
```

Use region `eu`, `us`, `kr`, or `tw`. Realm slugs work; quote realm names containing spaces.

Retail uses [Raider.IO](https://raider.io/api) and shows equipped item level, current Mythic+ score, raid progression, and a profile link. No API key is required. Classic and WoW Forever character cards are not included.

## FFXIV Price Trends

```text
!xivtrend Light Yollal Extract
!xivtrend Omega Dark Matter --nq
!xivtrend Light Yollal Extract --hq
```

Uses [Universalis](https://docs.universalis.app/) with no API key. NQ is the default; HQ must be requested explicitly, so different qualities are never mixed. Shows the cheapest returned listing, its difference from the last 24-hour sale median, sales medians for the last 24 hours and preceding 24 hours, observed units sold, and data freshness.

The trend compares sale medians only when both windows contain at least three transactions. Each transaction has equal weight regardless of stack size. Up to 1,000 sales are sampled over 48 hours; busy items may have an incomplete earlier window. These are community-observed sales, not a guaranteed full history or a price forecast.

Game API commands have per-user cooldowns, request timeouts, and helpful errors for unavailable profiles, rate limits, and missing data.

## FFXIV Market Watcher

The market watcher uses:

- **XIVAPI** to resolve an item name to its FFXIV item ID.
- **Universalis** to retrieve current market-board listings.

No API key is required for these integrations.

### Check a price

```text
!xivprice Light Yollal Extract
```

This returns the cheapest current **price per item** for Yollal Extract across the Light data center, including the world where the listing was found.

### Create a price alert

```text
!xivwatch Light 2800 Yollal Extract
```

The bot checks active watches every **5 minutes**.

When Yollal Extract reaches **2,800 gil per item or lower**, the bot pings the user who created the watch and removes that watch automatically.

For a strictly-under-2,800 alert:

```text
!xivwatch Light 2799 Yollal Extract
```

### View watches

```text
!xivwatches
```

Example:

```text
a42f19 — Yollal Extract on Light <= 2,800 gil
```

### Remove a watch

```text
!xivunwatch a42f19
```

## Environment Variables

The bot reads configuration from environment variables.

| Variable | Required | Description |
|---|---:|---|
| `DISCORD_BOT_TOKEN` | Yes | Discord bot token |
| `GEMINI_API_KEY` | For image checks | Google Gemini API key used when someone mentions Horsie for an image reality check |
| `REALITY_CHECK_MODEL` | No | Gemini image assessment model; defaults to `gemini-3.8-flash` |
| `TRAMPLE_ALL_MAX_MESSAGES` | No | Maximum messages deleted by `!trample all`; default is `1000` |
| `CARROT_FILE` | No | Path to carrot data; defaults to `carrots.json` on the Railway volume, or `data/carrots.json` locally |
| `FOREVER_CONFIG_FILE` | No | Path to WoW countdown config; defaults to `forever_countdown.json` on the Railway volume, or `data/forever_countdown.json` locally |
| `XIV_WATCH_FILE` | No | Path to FFXIV market watches; defaults to `xiv_watches.json` on the Railway volume, or `data/xiv_watches.json` locally |
| `HORSE_ARTICLE_FILE` | No | Path to shared article history; defaults to `horse_articles.json` on the Railway volume, or `data/horse_articles.json` locally |

Never commit your Discord bot token to GitHub.

## Python Requirements

Dependencies:

```text
discord.py
aiohttp
Pillow
```

Install locally with:

```powershell
pip install -r requirements.txt
```

## Run Locally

Set the required variables:

```powershell
$env:DISCORD_BOT_TOKEN="YOUR_TOKEN"

python main.py
```

## Railway Deployment

The bot can run continuously on Railway.

Recommended Railway variables:

```text
DISCORD_BOT_TOKEN=...
```

Start command:

```text
python main.py
```

If the Railway service is connected to GitHub, pushing a commit normally triggers a new deployment automatically.

```powershell
git add .
git commit -m "Update bot"
git push
```

## Persistent Storage on Railway

The bot currently stores carrots, countdown configuration, and FFXIV watches in JSON files.

Containers can be replaced during deployments, so use a Railway Volume if you want this data to survive redeployments.

All saves and login cooldown state automatically use `RAILWAY_VOLUME_MOUNT_PATH` when a volume is attached, or the project's `data/` folder locally. Explicit file path variables take priority. Runtime saves are excluded from Git; deployments do not ship old balances or local countdown settings. Saves are written to a temporary file and replaced atomically, and invalid carrot data raises an error rather than silently discarding scores.

When moving an existing bot to a volume, back up its live `carrots.json` and `horse_articles.json` and upload them to the volume before deploying. A new empty save starts with zero carrots; attaching a volume cannot recover previously lost wins automatically.

Example volume mount:

```text
/data
```

Recommended variables:

```text
CARROT_FILE=/data/carrots.json
FOREVER_CONFIG_FILE=/data/forever_countdown.json
XIV_WATCH_FILE=/data/xiv_watches.json
HORSE_ARTICLE_FILE=/data/horse_articles.json
```

## Discord Permissions

The bot needs normal permissions to view and send messages.

Additional features require:

- `!forevercd` → **Manage Channels**
- `!trample` → **Manage Messages**

The application should also have the Discord bot scope enabled for Guild Install. The Python bot uses message content, so the required Message Content intent must be enabled for the application.

## WoW Forever Countdown

Run:

```text
!forevercd
```

The bot asks which text channel should become the countdown.

It renames the selected channel automatically until the configured WoW Forever launch time. Each server can configure its own countdown channel with `!forevercd`. Settings are stored separately per server. Existing countdown channels and the original single-channel configuration are recovered automatically after restarts.

## Notes

FFXIV market data comes from community services and may not always represent an instantaneous in-game market-board state.

Horsie Bot is an independent hobby project and is not affiliated with Discord, Square Enix, Blizzard Entertainment, Railway, XIVAPI, Universalis, or Raider.IO.

## Tests

```text
python -m unittest discover -s tests -t .
```

Tests mock external services and Discord. They cover quality filtering, sales windows, retail cards, HTTP failures, simultaneous race picks, race concurrency, listener cleanup, macaroni horse uploads and phrase matching, text variation, and the earlier multi-server behavior without posting messages or requiring API credentials.
