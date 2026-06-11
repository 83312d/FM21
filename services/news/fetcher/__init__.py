"""RSS fetch, normalize, and dedup helpers (U16)."""

from services.news.fetcher.dedup import IngestResult, ingest_article
from services.news.fetcher.normalize import content_hash, normalize_content, normalize_url
from services.news.fetcher.rss import FetchedEntry, fetch_feed, resolve_entry_body

__all__ = [
    "FetchedEntry",
    "IngestResult",
    "content_hash",
    "fetch_feed",
    "ingest_article",
    "normalize_content",
    "normalize_url",
    "resolve_entry_body",
]
