"""Collect race picks independently of slow Discord sends and edits."""

import asyncio

import discord


def winner_pages(winners, limit=1800):
    """Keep large race results below Discord's message limit."""
    page = []
    size = 0
    for winner in winners:
        if page and size + len(winner) + 1 > limit:
            yield "\n".join(page)
            page, size = [], 0
        page.append(winner)
        size += len(winner) + 1
    if page:
        yield "\n".join(page)


class RaceBets:
    def __init__(self, channel_id, horses, clock):
        self.channel_id = channel_id
        self.horses = horses
        self.clock = clock
        self.deadline = float("inf")
        self.closed = False
        self.bets = {}
        self.revision = 0

    async def on_message(self, message):
        # No network calls or awaits here: every dispatched pick is recorded
        # even while the race command is waiting for Discord to edit the board.
        if (self.closed or self.clock() >= self.deadline
                or message.channel.id != self.channel_id or message.author.bot):
            return
        text = message.content.strip()
        if text not in {"1", "2", "3", "4"}:
            return
        self.bets[message.author.id] = {
            "user_id": message.author.id,
            "name": message.author.display_name,
            "choice": int(text),
        }
        self.revision += 1

    def render(self):
        lines = ["🏇 **Horse Race!**", ""]
        for number, horse in enumerate(self.horses, 1):
            count = sum(bet["choice"] == number for bet in self.bets.values())
            lines.append(f"{number}. **{horse}** — {count} pick(s)")
        lines.extend(["", f"🎟️ **{len(self.bets)} players** have picked a horse."])
        if self.closed:
            lines.append("🔒 **Bets are locked!**")
        else:
            lines.extend([
                "Send a number from **1** to **4**. Your latest pick counts.",
                "You have **20 seconds**. Picks are collected continuously; this board refreshes every 2 seconds.",
                "Correct guesses earn 🥕 **1 carrot**.",
            ])
        return "\n".join(lines)


async def collect_race_bets(bot, ctx, horses, duration=20, refresh_interval=2):
    loop = asyncio.get_running_loop()
    collector = RaceBets(ctx.channel.id, horses, loop.time)
    listener = collector.on_message
    # Register before the announcement so fast replies are not missed.
    bot.add_listener(listener, "on_message")
    try:
        board = await ctx.send(collector.render())
        collector.deadline = loop.time() + duration
        shown_revision = 0
        while True:
            remaining = collector.deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(refresh_interval, remaining))
            if loop.time() >= collector.deadline:
                break
            if collector.revision == shown_revision:
                continue
            shown_revision = collector.revision
            try:
                await board.edit(content=collector.render())
            except discord.HTTPException:
                # A deleted board or failed edit must not interrupt collection.
                pass
    finally:
        collector.closed = True
        bot.remove_listener(listener, "on_message")

    try:
        await board.edit(content=collector.render())
    except discord.HTTPException:
        pass
    return collector.bets
