"""URL and content normalization for news dedup (U16, ADR-004)."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_url(url: str) -> str:
    """Strip tracking params and normalize host/scheme for dedup."""
    trimmed = url.strip()
    if not trimmed:
        return trimmed

    parsed = urlparse(trimmed)
    if not parsed.scheme or not parsed.netloc:
        return trimmed

    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query=urlencode(filtered_query, doseq=True),
        fragment="",
    )
    return urlunparse(normalized)


def normalize_content(text: str) -> str:
    """Collapse whitespace for stable content hashing."""
    return _WHITESPACE_RE.sub(" ", text.strip())


def content_hash(text: str) -> str | None:
    """SHA-256 of normalized article body; None when body is empty."""
    normalized = normalize_content(text)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
