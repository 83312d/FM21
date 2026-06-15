"""Parse /order command text — Title — Artist (dash separator)."""

from __future__ import annotations

import re

# Em dash, en dash, or ASCII hyphen surrounded by optional whitespace.
ORDER_SEPARATOR_PATTERN = re.compile(r"\s*[—–-]\s*")


def parse_order_args(args: list[str]) -> tuple[str, str] | None:
    """Return (title, artist) or None when format is invalid."""
    if not args:
        return None

    text = " ".join(args).strip()
    parts = ORDER_SEPARATOR_PATTERN.split(text, maxsplit=1)
    if len(parts) != 2:
        return None

    title, artist = parts[0].strip(), parts[1].strip()
    if not title or not artist:
        return None
    return title, artist


def format_search_query(title: str, artist: str) -> str:
    return f"{title} {artist}".strip()
