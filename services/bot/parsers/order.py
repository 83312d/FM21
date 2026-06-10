"""Parse /order command text — Title — Artist (em dash separator)."""

from __future__ import annotations

ORDER_SEPARATOR = "—"


def parse_order_args(args: list[str]) -> tuple[str, str] | None:
    """Return (title, artist) or None when format is invalid."""
    if not args:
        return None

    text = " ".join(args).strip()
    if ORDER_SEPARATOR not in text:
        return None

    title, artist = text.split(ORDER_SEPARATOR, 1)
    title = title.strip()
    artist = artist.strip()
    if not title or not artist:
        return None
    return title, artist


def format_search_query(title: str, artist: str) -> str:
    return f"{title} {artist}".strip()
