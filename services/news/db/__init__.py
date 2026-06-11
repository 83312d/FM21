"""News persistence layer (U15)."""

from services.news.db.models import (
    InvalidNewsStatusTransition,
    NewsFetchInput,
    NewsItem,
    NewsItemStatus,
)
from services.news.db.repository import NewsItemRepository

__all__ = [
    "InvalidNewsStatusTransition",
    "NewsFetchInput",
    "NewsItem",
    "NewsItemRepository",
    "NewsItemStatus",
]
