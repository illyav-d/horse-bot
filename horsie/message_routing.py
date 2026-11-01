"""Shared routing so a mention receives exactly one kind of AI response."""

import re


def mention_text(content, bot_id):
    return re.sub(rf"<@!?{bot_id}>", "", content).strip()


def is_image_check(content, bot_id):
    if not re.search(rf"<@!?{bot_id}>", content):
        return False
    text = mention_text(content, bot_id).lower()
    return not text or bool(re.search(
        r"\b(?:is\s+(?:this|that|it)\s+(?:real|ai|fake|authentic)|"
        r"real\s+or\s+ai|ai\s+or\s+real|if\s+it['’]?s\s+real)\b", text))
