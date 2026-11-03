# Horsie Bot 🐴

A small Discord bot with horse-themed commands, games, a WoW Forever countdown, and an FFXIV market-board watcher.

Current version: **1.9.3**

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
- Ping Horsie to assess your latest image or GIF for signs of AI generation

## Version 1.9.3

- Horsie automatically switches chat models when one is busy or unavailable.

## Version 1.9.2

- Horsie chats more efficiently and lets server admins check AI usage.

## Version 1.9.1

- Horsie keeps replies focused on your question and retries blank answers with shorter context.

## Version 1.9.0

- Horsie now keeps lasting channel memories and notes you can review or forget.

## Version 1.8.12

- Horsie now remembers recent channel conversations after a reboot.

## Version 1.8.11

- Horsie automatically retries empty AI replies before asking you to try again.

## Version 1.8.10

- Horsie now follows the whole channel with shared conversation memory.

## Version 1.8.9

- Mention or reply to chat with Horsie; web search is disabled.

## Version 1.8.8

- Full-GIF sampling and longer picture explanations.

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
| `@Horsie` or `@Horsie is this real?` | Assesses your latest image or GIF in this channel for possible AI generation |
| `@Horsie <message>` | Chats with Horsie; reply to its chat messages to continue |
| `@Horsie usage` | Shows today's and the last seven UTC days' bot AI usage; requires Manage Server |

## Chat with Horsie

Mention Horsie with a message, for example `@Horsie how's your day?`, then use Discord's Reply on its answer to continue without another ping. Horsie responds only when invited, with short, friendly replies and occasional horse humor. Chat is available in server channels; DMs are ignored.

Horsie follows new human text messages throughout the channel, including messages without a ping, using one shared conversation for everyone. Anyone can reply to Horsie's chat answers to continue. Messages are labelled with their speaker's display name, user ID, message ID and replied-to message ID so Horsie can follow who said what. It still only answers when mentioned or replied to; ordinary messages do not trigger chat replies. Bots, webhooks and DMs are ignored. Background summaries use occasional AI calls as described below.

Memory holds up to 40 messages (human messages and Horsie's chat answers), at most 24,000 text characters per channel. Each message expires after 30 minutes, including time spent offline. Up to 128 channel memories are retained, with older channels evicted first. Channel text, speaker labels and reply IDs are saved atomically after each message in `horse_chat_memory.json` on the Railway volume (locally, `data/horse_chat_memory.json`). Set `HORSE_CHAT_MEMORY_FILE` to override the path. Recent context and reply follow-ups reload after a restart; expired messages are discarded on load and cleaned from storage every minute while running. It does not backfill Discord history. Channels, threads and servers have separate memories. When asked to respond, Horsie sends this recent shared channel context to Groq. Attachments are not read for chat. Horsie cannot browse or perform bot commands through chat.

Each answer sends a smaller view of recent history: at most 12 earlier messages and 6,000 characters, with individual earlier messages excerpted at 2,000 characters. An older human message being replied to gets priority within that budget. The current question and personality instructions are preserved. The full saved history is unchanged. The current question is sent as dialogue to avoid Qwen returning blank replies to JSON-wrapped questions. With backups disabled, a blank answer gets at most one retry with up to four earlier messages and 2,000 history characters, keeping recalled notes and the current question.

Chat normally tries Qwen first, then `openai/gpt-oss-20b`, then `openai/gpt-oss-120b`, stopping at the first visible answer. These are sequential attempts, not three answers generated for every message. Each receives the same personality instructions, question and memory context; conversational style can still vary by model. A model can fail over on rate limits, temporary server/network errors, timeouts, unavailable-model errors or empty answers. Invalid credentials, access denials, request errors and content-filter responses stop the request. At most three models are tried, one attempt each, with eight seconds per API attempt and 30 seconds overall. GPT-OSS uses low reasoning effort for chat. Model cooldowns are separate: a busy primary is skipped until its cooldown expires, then preferred again. If every model is rate-limited, chat waits for the earliest model cooldown to end. Set `GROQ_CHAT_FALLBACK_MODELS` to a comma-separated list to customize backups, or an empty value to disable them. The primary plus unique backups are capped at three models. Image checks keep their own vision model and do not use these text-only backups.

Background memory summaries use only the primary model, reserving backups for chat. A summary quota error pauses summaries rather than preventing chat from using a backup. Failover consumes tokens only for attempts actually made, and each model's usage appears in `@Horsie usage`.

Chat uses the existing `GROQ_API_KEY`, with `qwen/qwen3.8-27b` by default (see [Groq's text chat documentation](https://console.groq.com/docs/text-chat)). Set `GROQ_CHAT_MODEL` to override it. Each channel and person can have one request in progress, and each person must wait five seconds after a successful reply before asking again. Up to three chat requests run at once, with a 30-second API timeout. Failed requests can be retried immediately unless Groq has imposed a quota pause; chat, summaries and image checks consume the account's API quota.

## AI Usage

Mention Horsie with `usage`, `ai usage` or `token usage` to see reported input/output tokens, cached input tokens, API attempts, retries, errors and rate-limit responses. This local request requires Manage Server permission and makes no AI call. The report shows today's totals by chat, memory summaries and image checks, plus the last seven UTC days' total. It covers the whole bot, across servers. Cached tokens are a subset of input tokens and are not counted twice. Each attempt is counted, including blank responses, retries and transport failures; attempts without valid provider token counts are explicitly marked as unreported rather than estimated as free.

Daily aggregates are retained for 31 UTC dates, separated by feature and model, in `horse_ai_usage.json` on the Railway volume (locally `data/horse_ai_usage.json`). Set `HORSE_AI_USAGE_FILE` to override the path. Writes are atomic and survive restarts. No prompts, answers, images, user IDs or credentials are stored in this ledger. Tracking begins when this version runs: it cannot recover earlier consumption, include other applications' usage or establish the account's remaining quota. Storage failures are logged and shown in the report; live counters are retained for the next save attempt.

## Lasting Memories

Mention Horsie or reply to its chat answer with these requests:

| Request | Behavior |
|---|---|
| `remember I like horse racing` | Saves your personal note in this server |
| `remember for the channel Friday is race night` | Saves a shared note for this channel |
| `memories` or `what do you remember?` | Shows your notes, this channel's shared notes, and its summary |
| `forget <ID>` | Removes a saved note by its displayed ID |
| `forget my memories` | Clears your personal notes in this server |
| `forget channel` | Clears shared notes, the summary, and recent context in this channel; requires Manage Messages |

Saved notes have no time-based expiry and survive reboots. Personal notes are recalled only for their owner, within the same server. Shared notes and summaries stay in their original channel or thread; they are never recalled across servers. A note's creator can delete it; moderators can also delete shared channel notes. Memory requests are handled by the bot directly, so its acknowledgement reflects an actual save or deletion. Note commands are excluded from automatic summarization. The model receives stored memories as untrusted background, with recent corrections taking priority. Up to five relevant or recent notes are recalled per answer within a 1,800-character JSON allowance, alongside the channel summary. Other saved notes remain available through `memories`.

Horsie also periodically condenses human channel messages into a short, evolving summary of recurring jokes, shared interests and ongoing group plans. One channel is summarized per minute at most, after 12 new human messages, or at least four messages nearing recent-context expiry. Each channel waits at least ten minutes between attempts, including failures. Each attempt processes up to 6,000 characters of human context, in chronological order, excerpting individual messages at 1,000 characters; newer omitted messages remain eligible for the next batch while in recent memory. Blank summary responses are not immediately retried, and JSON output mode helps avoid invalid results. Busy chat and quota pauses defer this work. Summaries are generated by AI, can be incomplete or mistaken, and are instructed to avoid secrets, sensitive personal details and personal profiles. They are not a full transcript. Invalid summary results keep the previous memory. There is no history backfill.

The same persistent memory file holds notes and summaries. Limits are 500 characters per note, 50 personal notes per owner/server, 50 shared notes per channel, and 2,048 notes in total. Full note storage asks users to forget older notes rather than silently replacing them. Up to 128 channel summaries are retained, each under 1,500 characters, with the oldest updated summary replaced when that limit is reached. Summaries are automatically revised as conversation changes and can be cleared by a moderator. Recent chat still uses its existing 30-minute expiry. Background summaries use the configured Groq chat model and consume API quota; no new key is needed.

## Image Reality Checks

Post or link an image or GIF, then ping `@Horsie` (select the actual bot mention in Discord). A bare mention or an image-check question such as `@Horsie is this real?`, `is it real?`, or `real or AI?` starts a check. Other text with a mention starts a chat instead. An image or link in the check question takes priority. Otherwise, Horsie checks only the asking user's five previous messages in that channel, newest first, stopping at the first image or GIF. Other people's messages do not count toward those five and their images are never selected, including when replying to another person. If none of your five messages has readable media, Horsie says so. Each request selects its own media; it never reuses the last person's image. The answer links the checked message.

Uploads, direct HTTPS image/GIF links (including Markdown links), extensionless image URLs, and Discord image/GIF previews are recognized. When Discord has not created a preview, Horsie can open a linked page and read its Open Graph/Twitter image metadata, including image-sharing pages such as Tenor and Giphy. It tries at most three page links per message, reads up to 256 KB of each page, validates public HTTPS destinations and redirects, and caps the entire message/link lookup at 15 seconds. Pages requiring login or lacking readable image metadata may still need a direct image link.

An admin must set `GROQ_API_KEY` on the host (Railway service > Variables). Create a key in [Groq Console](https://console.groq.com/keys). The default vision model is `qwen/qwen3.8-27b`; `GROQ_REALITY_CHECK_MODEL` optionally overrides it with a Groq vision model supporting strict structured output and disabled reasoning. The selected images are downloaded and sent to Groq for analysis. This uses [Groq's image input API](https://console.groq.com/docs/vision). Gemini configuration is no longer used by this feature. No API key is stored in the repository.

Groq offers a [free plan with request and token limits](https://console.groq.com/docs/rate-limits). The Qwen vision model counts each image or sampled GIF frame as 2,048 input tokens; token limits can be reached before the request ceiling. For quota errors, Horsie uses the `Retry-After` header or retry duration in the response (60 seconds if none is provided) and distinguishes explicit daily quotas from short-term limits. It pauses new API checks across the bot during that delay. Temporary server failures (including HTTP 503), explicit structured-output generation failures (`json_validate_failed`), and connection failures are retried up to twice, with short exponential delays and jitter. API attempts share a 40-second deadline inside the existing 55-second overall check limit. Invalid keys, access errors, model errors and quota errors are not retried.

Successful assessments of the exact same image URLs, server and model are cached in memory for 30 minutes, up to 128 entries, and can still be returned during a quota pause. Each request first selects the asking user's own media; cached results never choose another person's image. Concurrent checks share one API operation at a time. No images or results are written to disk by this cache, and restart clears it. These measures reduce duplicate usage; they cannot increase Groq's free quota. The model describes the visible subjects, actions, setting and distinctive details before explaining its verdict. Each check uses one assessment by default to conserve the shared quota. Set `GROQ_REALITY_CHECK_REVIEW=true` to enable at most one independent second look for inconclusive or flagged ambiguous results, with different GIF/WebP frames where available. This optional review can nearly double token usage for uncertain checks. The output token allowance is capped at 2048 for the scene description and explanation, with prompt budgets of 1050 characters for observations and 1800 for reasons. Conflicting or unresolved checks return Inconclusive. The optional review has at most 12 seconds within the overall 55-second check limit; failure preserves the first usable answer, and review quota errors still pause new checks. See [the evaluation guide](docs/REALITY_CHECK_EVALUATION.md) for the five-case regression set and live evaluation runner.

Horsie gives a **Likely AI-generated**, **Likely authentic**, or **Inconclusive** assessment followed by a **What I see** scene description and a **Why** explanation of the visible clues and uncertainty, without a generic disclaimer footer. Longer replies are split across Discord messages rather than cut off. It does not verify factual claims, search for originals or authenticate provenance. JPG, PNG, WebP and GIF uploads, direct HTTPS image links, and images exposed by link previews are supported, with up to three images per message, an 8 MB limit per image and a 12 MB combined image limit. Downloads require public HTTPS URLs, validate redirects and file signatures, and enforce size limits while streaming. Groq receives at most three image inputs per API call. Each GIF or animated WebP uses one labelled storyboard grid with up to 12 frames spread across playback time. The first and final frames are always included, even during optional review; repeated samples of a long-held frame are filled with well-spaced unseen frames. Short animations show every frame when there are at most 12. Each tile is scaled to at most 480 pixels per side and the grid uses lossless PNG to avoid adding JPEG artifacts. This samples the full animation span; it does not inspect every frame of longer animations. The prompt distinguishes ordinary GIF palette, transparency and motion-blur artifacts from evidence of AI generation. Multiple animations each keep their own storyboard within the three-image input budget, without extra API calls. It supports Imgur single-image sharing links, direct image/GIF/GIFV links, album/gallery cover metadata when readable, uploaded GIFs, direct GIF URLs, Tenor/Giphy GIF previews, and Klipy animated WebP previews exposed by Discord. Animated WebPs use the same storyboard sampling as GIFs. GIF decoding runs off the Discord event loop, with limits of 200 GIF frames or 400 animated WebP frames, 16 million pixels per frame, and 100 million total frame pixels; larger animations need a shorter GIF or screenshot. Videos and links without a readable image need a screenshot or direct image/GIF upload. Only the selected images are analyzed; surrounding chat and image captions are not submitted. Each person can request one successful check every 30 seconds, with an explicit cooldown reply for repeat requests. Failed checks, missing images, missing API configuration, and full queues do not consume the personal cooldown; a failed request can be corrected and retried immediately. A real Groq quota pause still applies across users until its retry delay expires, even when nobody is currently asking for checks. Up to three requests can be active or waiting across the bot, including in the same channel. Requests share one API operation at a time; waiting requests receive an acknowledgement, and a full queue gets an explicit retry message. The bot needs Read Message History and permission to send replies. Without an API key, this feature explains that it is not connected; other features continue working.

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
| `GROQ_API_KEY` | For image checks and chat | Groq API key used for AI image checks and conversation |
| `GROQ_CHAT_MODEL` | No | Text chat model; defaults to `qwen/qwen3.8-27b` |
| `GROQ_CHAT_FALLBACK_MODELS` | No | Comma-separated chat backups; defaults to `openai/gpt-oss-20b,openai/gpt-oss-120b`; empty disables backups |
| `HORSE_CHAT_MEMORY_FILE` | No | Persistent channel memory path; defaults to `horse_chat_memory.json` on the Railway volume, or `data/horse_chat_memory.json` locally |
| `HORSE_AI_USAGE_FILE` | No | Persistent AI usage totals; defaults to `horse_ai_usage.json` on the Railway volume, or `data/horse_ai_usage.json` locally |
| `GROQ_REALITY_CHECK_MODEL` | No | Groq vision model; defaults to `qwen/qwen3.8-27b` |
| `GROQ_REALITY_CHECK_REVIEW` | No | Set to `true` to enable an extra assessment for uncertain results; disabled by default to conserve quota |
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
