"""Bounded channel memory snapshots with restart-safe timestamps."""

import json
import math
from collections import OrderedDict

def load_memory(path, now, wall_now, ttl, max_channels, max_messages, max_chars):
    sessions = OrderedDict()
    try:
        if not path.exists():
            return sessions
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("oversized memory file")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("channels"), list):
            raise ValueError("invalid memory format")
        for channel in data["channels"][-max_channels:]:
            if not isinstance(channel, dict):
                continue
            guild, cid = channel.get("guild_id"), channel.get("channel_id")
            if not all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in (guild, cid)):
                continue
            messages, replies = [], []
            entries = channel.get("messages", [])
            if not isinstance(entries, list):
                continue
            for entry in entries[-max_messages:]:
                if not isinstance(entry, dict) or not isinstance(entry.get("payload"), dict):
                    continue
                at, payload = entry.get("at"), entry["payload"]
                role = payload.get("role")
                if not valid_time(at, wall_now, ttl) or not isinstance(role, str) or role not in {"user", "assistant"}:
                    continue
                content = payload.get("content")
                if not isinstance(content, str) or not content:
                    continue
                messages.append({"at": now + at - wall_now,
                                 "payload": {"role": payload["role"], "content": content[:max_chars]}})
            while sum(len(entry["payload"]["content"]) for entry in messages) > max_chars:
                messages.pop(0)
            raw_replies = channel.get("replies", [])
            if isinstance(raw_replies, list):
                for reply in raw_replies[-24:]:
                    if not isinstance(reply, list) or len(reply) != 2:
                        continue
                    at, mid = reply
                    if valid_time(at, wall_now, ttl) and isinstance(mid, int) and not isinstance(mid, bool) and mid > 0:
                        replies.append((now + at - wall_now, mid))
            if messages:
                sessions[(guild, cid)] = {"messages": messages, "replies": replies}
    except (OSError, ValueError, TypeError) as error:
        print(f"Horsie chat memory could not load: {type(error).__name__}", flush=True)
    return sessions


def valid_time(at, wall_now, ttl):
    return (isinstance(at, (int, float)) and not isinstance(at, bool)
            and math.isfinite(at) and 0 <= wall_now - at < ttl)


def memory_snapshot(sessions, now, wall_now):
    # Copy data before a background write; subsequent channel messages stay in RAM.
    offset = wall_now - now
    return {"version": 1, "channels": [
        {"guild_id": guild, "channel_id": channel,
         "messages": [{"at": entry["at"] + offset, "payload": dict(entry["payload"])}
                      for entry in state["messages"]],
         "replies": [[at + offset, mid] for at, mid in state["replies"]]}
        for (guild, channel), state in sessions.items()
    ]}
