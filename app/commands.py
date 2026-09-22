from __future__ import annotations

import re

from telegram.ext import filters

COMMAND_RE = re.compile(r"^/([A-Za-z0-9_]+)(?:@([A-Za-z0-9_]+))?(?:\s|$)")


def command_filter(name: str) -> filters.Regex:
    return filters.Regex(re.compile(rf"^/{re.escape(name)}(?:@[A-Za-z0-9_]+)?(?:\s|$)", re.IGNORECASE))


def parse_command(text: str | None) -> tuple[str, str | None] | None:
    if not text:
        return None
    match = COMMAND_RE.match(text.strip())
    if not match:
        return None
    return match.group(1).lower(), match.group(2)
