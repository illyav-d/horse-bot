"""Persistent provider-reported token totals, without prompts or user identities."""

import asyncio
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import aiohttp

from horsie.data_storage import data_path, write_json


FIELDS = ("requests", "retries", "errors", "rate_limits", "unreported", "input", "output", "cached", "total")


def count(value):
    return value if type(value) is int and value >= 0 else 0


class UsageLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.days = {}
        self.saved = True
        self.history_incomplete = False
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                for day, rows in raw.get("days", {}).items():
                    datetime.strptime(day, "%Y-%m-%d")
                    if not isinstance(rows, dict):
                        continue
                    self.days[day] = {key: {field: count(row.get(field)) for field in FIELDS}
                                      for key, row in rows.items() if isinstance(row, dict)}
        except (OSError, ValueError, TypeError, AttributeError):
            self.saved = False
            self.history_incomplete = True
            print("Horsie AI usage could not load; historical totals may be incomplete.", flush=True)

    def record(self, feature, model, status, body=None, retry=False, now=None):
        now = now or datetime.now(timezone.utc)
        usage = body.get("usage") if isinstance(body, dict) else None
        reported = (isinstance(usage, dict) and type(usage.get("prompt_tokens")) is int
                    and type(usage.get("completion_tokens")) is int
                    and usage["prompt_tokens"] >= 0 and usage["completion_tokens"] >= 0)
        usage = usage if reported else {}
        details = usage.get("prompt_tokens_details")
        details = details if isinstance(details, dict) else {}
        increment = dict(requests=1, retries=int(retry), errors=int(status != 200),
                         rate_limits=int(status == 429), unreported=int(not reported),
                         input=count(usage.get("prompt_tokens")), output=count(usage.get("completion_tokens")),
                         cached=count(details.get("cached_tokens")),
                         total=count(usage.get("prompt_tokens")) + count(usage.get("completion_tokens")))
        with self.lock:
            row = self.days.setdefault(now.date().isoformat(), {}).setdefault(
                feature + ":" + model, dict.fromkeys(FIELDS, 0))
            for field, value in increment.items():
                row[field] += value
            cutoff = (now.date() - timedelta(days=30)).isoformat()
            self.days = {day: rows for day, rows in self.days.items() if day >= cutoff}
            try:
                write_json(self.path, {"version": 1, "days": self.days})
                self.saved = True
            except OSError:
                self.saved = False
                print("Horsie AI usage could not save; totals remain in memory until the next save.", flush=True)

    def report(self, now=None):
        now = now or datetime.now(timezone.utc)
        today = now.date().isoformat()
        cutoff = (now.date() - timedelta(days=6)).isoformat()
        with self.lock:
            rows = self.days.get(today, {})
            totals = {field: sum(row[field] for row in rows.values()) for field in FIELDS}
            week = sum(row["total"] for day, entries in self.days.items() if cutoff <= day <= today
                       for row in entries.values())
            lines = [f"AI usage today ({today}, UTC; whole bot):",
                     f"{totals['total']:,} reported tokens: {totals['input']:,} input + {totals['output']:,} output.",
                     f"{totals['requests']:,} API attempts, including {totals['retries']:,} retries; "
                     f"{totals['errors']:,} errors ({totals['rate_limits']:,} rate limits)."]
            for feature, label in (("chat", "Chat"), ("summary", "Memory summaries"), ("image", "Image checks")):
                selected = [row for key, row in rows.items() if key.startswith(feature + ":")]
                lines.append(f"{label}: {sum(row['total'] for row in selected):,} tokens / "
                             f"{sum(row['requests'] for row in selected):,} attempts.")
            models = sorted({key.split(":", 1)[1] for key in rows})
            for model in models[:5]:
                selected = [row for key, row in rows.items() if key.split(":", 1)[1] == model]
                lines.append(f"{model}: {sum(row['total'] for row in selected):,} tokens / "
                             f"{sum(row['requests'] for row in selected):,} attempts.")
            lines += [f"Last 7 UTC days: {week:,} reported tokens.",
                      f"{totals['cached']:,} cached input tokens (already included in input).",
                      f"{totals['unreported']:,} attempts today had no token counts; totals may be incomplete.",
                      "Tracks this bot since tracking began; excludes other apps and earlier usage. "
                      "This is usage, not your remaining Groq quota."]
            if not self.saved:
                lines.append("Usage storage needs attention; totals may not survive a restart.")
            if self.history_incomplete:
                lines.append("Earlier usage could not be loaded; historical totals are incomplete.")
            return "\n".join(lines)


@lru_cache(maxsize=4)
def ledger_for(path):
    return UsageLedger(path)


def usage_ledger():
    return ledger_for(str(data_path("HORSE_AI_USAGE_FILE", "horse_ai_usage.json")))


async def record_api_usage(feature, model, status, body=None, retry=False):
    # Disk I/O runs off the Discord event loop; one lock serializes all features.
    await asyncio.to_thread(usage_ledger().record, feature, model, status, body, retry)


async def usage_report():
    return await asyncio.to_thread(usage_ledger().report)


async def groq_request(session, model, payload, feature, retry=False):
    """Measure every HTTP attempt, including empty replies and retries."""
    status, body = 0, None
    try:
        async with session.post(
            "https://api.groq.com/openai/v1/chat/completions", json=payload,
            headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"].strip()},
            allow_redirects=False,
        ) as response:
            status = response.status
            try:
                body = await response.json()
            except (aiohttp.ClientError, ValueError):
                if status == 200:
                    raise
                body = {}
            return status, body, getattr(response, "headers", {})
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        status = 0
        raise
    finally:
        await record_api_usage(feature, model, status, body, retry)
