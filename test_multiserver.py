import asyncio, json, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import discord
import horse_bot as h

def channel(i, name="general", allowed=True):
    c = Mock(spec=discord.TextChannel)
    c.id, c.name = i, name
    c.guild = SimpleNamespace(me=object())
    c.permissions_for.return_value = SimpleNamespace(view_channel=allowed, send_messages=allowed, embed_links=allowed, attach_files=allowed)
    c.send = AsyncMock()
    c.edit = AsyncMock()
    return c

def guild(i, channels):
    return SimpleNamespace(id=i, me=object(), text_channels=channels, get_channel=lambda cid: next((c for c in channels if c.id == cid), None))

async def main():
    c1, c2 = channel(11, "wow-forever-1d-00h"), channel(22, "wow-forever-1d-00h")
    g1, g2 = guild(1, [c1]), guild(2, [c2])
    with tempfile.TemporaryDirectory() as tmp, patch.object(h, "FOREVER_CONFIG_FILE", Path(tmp)/"config.json"), patch.object(h.bot, "_connection") as state:
        state.guilds = [g1, g2]
        h.FOREVER_CONFIG_FILE.write_text(json.dumps({"channel_id":11}))
        assert h.get_forever_channel_id(g1) == 11
        assert h.get_forever_channel_id(g2) == 0
        await h.update_forever_countdown.coro()
        assert h.load_forever_config()["channels"] == {"1":11,"2":22}
        c1.edit.assert_awaited_once()
        c2.edit.assert_awaited_once()
        await h.post_changelog_to_discord()
        c1.send.assert_awaited_once()
        c2.send.assert_awaited_once()
        for posted in [c1, c2]:
            payload = posted.send.call_args.kwargs
            assert payload["embed"].thumbnail.url == "attachment://changelog_rat.gif"
            assert payload["file"].filename == "changelog_rat.gif"
        with patch.object(h, "send_horse", AsyncMock()) as send:
            await h.post_daily_horse.coro()
            assert [call.args[0] for call in send.await_args_list] == [c1,c2]
        c1.edit.reset_mock()
        c2.edit.reset_mock()
        c1.edit.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "denied")
        await h.update_forever_countdown.coro()
        c2.edit.assert_awaited_once()
    blocked, first, second = channel(31, allowed=False), channel(32), channel(33)
    sender = AsyncMock(side_effect=[discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "denied"),None])
    await h.post_to_guild(guild(3,[blocked,first,second]), sender)
    assert [call.args[0] for call in sender.await_args_list] == [first,second]
    print("PASS: legacy migration, two-server countdowns and posts, permission filtering, send fallback, countdown failure isolation")

asyncio.run(main())
