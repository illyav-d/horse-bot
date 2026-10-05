# Horsie Bot 🐴

A small Discord bot with horse-themed commands, games, a WoW Forever countdown, and an FFXIV market-board watcher.

Current version: **1.7.0**

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
| `DISCORD_CHANNEL_ID` | Yes | Channel used for the scheduled daily horse and changelog |
| `TRAMPLE_ALL_MAX_MESSAGES` | No | Maximum messages deleted by `!trample all`; default is `1000` |
| `CARROT_FILE` | No | Path to carrot data; default is `carrots.json` |
| `FOREVER_CONFIG_FILE` | No | Path to WoW countdown config; default is `forever_countdown.json` |
| `XIV_WATCH_FILE` | No | Path to FFXIV market watches; default is `xiv_watches.json` |

Never commit your Discord bot token to GitHub.

## Python Requirements

At minimum:

```text
discord.py
aiohttp
```

Install locally with:

```powershell
pip install -r requirements.txt
```

## Run Locally

Set the required variables:

```powershell
$env:DISCORD_BOT_TOKEN="YOUR_TOKEN"
$env:DISCORD_CHANNEL_ID="YOUR_CHANNEL_ID"

python horse_bot.py
```

## Railway Deployment

The bot can run continuously on Railway.

Recommended Railway variables:

```text
DISCORD_BOT_TOKEN=...
DISCORD_CHANNEL_ID=...
```

Start command:

```text
python horse_bot.py
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

Example volume mount:

```text
/data
```

Recommended variables:

```text
CARROT_FILE=/data/carrots.json
FOREVER_CONFIG_FILE=/data/forever_countdown.json
XIV_WATCH_FILE=/data/xiv_watches.json
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

It renames the selected channel automatically until the configured WoW Forever launch time. Existing countdown channels can be detected again when the bot restarts.

## Notes

FFXIV market data comes from community services and may not always represent an instantaneous in-game market-board state.

Horsie Bot is an independent hobby project and is not affiliated with Discord, Square Enix, Blizzard Entertainment, Railway, XIVAPI, or Universalis.
