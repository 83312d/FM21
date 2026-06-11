"""RSS feed fetch and article body resolution (U16)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import feedparser
import httpx
from bs4 import BeautifulSoup

from services.news.fetcher.normalize import normalize_content, normalize_url

logger = logging.getLogger(__name__)

MIN_SNIPPET_LEN = 500
DEFAULT_TIMEOUT_SEC = 30.0
_USER_AGENT = "FM21-NewsFetcher/1.0"


@dataclass(frozen=True, slots=True)
class FetchedEntry:
    source_url: str
    title: str
    snippet: str


def _entry_link(entry: feedparser.FeedParserDict) -> str | None:
    link = entry.get("link")
    if isinstance(link, str) and link.strip():
        return link.strip()

    links = entry.get("links") or []
    for item in links:
        href = item.get("href") if isinstance(item, dict) else None
        if isinstance(href, str) and href.strip():
            return href.strip()
    return None


def _entry_snippet(entry: feedparser.FeedParserDict) -> str:
    """Extract plain text from RSS fields (same path as article HTML for stable hashing)."""
    for key in ("content", "summary", "description"):
        value = entry.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                body = first.get("value")
                if isinstance(body, str) and body.strip():
                    return extract_article_text(body)
        if isinstance(value, str) and value.strip():
            return extract_article_text(value)
    return ""


def _parse_feed_body(feed_body: str, *, feed_url: str) -> list[FetchedEntry]:
    parsed = feedparser.parse(feed_body, response_headers={"content-type": "application/rss+xml"})
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"malformed RSS from {feed_url}: {parsed.bozo_exception}")

    entries: list[FetchedEntry] = []
    for entry in parsed.entries:
        link = _entry_link(entry)
        if link is None:
            continue

        title = entry.get("title")
        entries.append(
            FetchedEntry(
                source_url=normalize_url(link),
                title=title.strip() if isinstance(title, str) else "",
                snippet=_entry_snippet(entry),
            )
        )
    return entries


async def fetch_feed(
    feed_url: str,
    *,
    client: httpx.AsyncClient,
    feed_body: str | None = None,
) -> list[FetchedEntry]:
    """Download and parse an RSS feed."""
    if feed_body is not None:
        return _parse_feed_body(feed_body, feed_url=feed_url)

    response = await client.get(feed_url, headers={"User-Agent": _USER_AGENT})
    response.raise_for_status()
    return _parse_feed_body(response.text, feed_url=feed_url)


def extract_article_text(html: str) -> str:
    """Best-effort main text extraction from article HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag_name in ("script", "style", "nav", "footer", "header", "aside"):
        for tag in soup.find_all(tag_name):
            tag.decompose()

    article = soup.find("article")
    root = article if article is not None else soup.body or soup
    return normalize_content(root.get_text(separator=" ", strip=True))


async def fetch_article_body(url: str, *, client: httpx.AsyncClient) -> str:
    response = await client.get(url, headers={"User-Agent": _USER_AGENT})
    response.raise_for_status()
    return extract_article_text(response.text)


async def resolve_entry_body(
    entry: FetchedEntry,
    *,
    client: httpx.AsyncClient,
    min_snippet_len: int = MIN_SNIPPET_LEN,
) -> str:
    """Use RSS snippet or fetch full article when snippet is too short."""
    if len(entry.snippet) >= min_snippet_len:
        return entry.snippet

    try:
        return await fetch_article_body(entry.source_url, client=client)
    except Exception:
        logger.warning("Article body fetch failed for %s", entry.source_url, exc_info=True)
        return entry.snippet
