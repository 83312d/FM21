"""News-domain types; ORM model lives in services.db.models (U9)."""

from __future__ import annotations

from dataclasses import dataclass

from services.db.models import NewsItem, NewsItemStatus

__all__ = [
    "InvalidNewsStatusTransition",
    "NewsFetchInput",
    "NewsItem",
    "NewsItemStatus",
]


class InvalidNewsStatusTransition(ValueError):
    """Raised when a news_items status change violates the pipeline workflow."""


@dataclass(frozen=True, slots=True)
class NewsFetchInput:
    """Payload from RSS ingest (U16) before summarization."""

    source_url: str
    content_hash: str | None = None
