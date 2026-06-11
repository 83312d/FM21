"""News items repository — workflow state and play tracking (U15)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.models import NewsItem, NewsItemStatus
from services.news.db.models import InvalidNewsStatusTransition, NewsFetchInput

_ALLOWED_TRANSITIONS: dict[NewsItemStatus, set[NewsItemStatus]] = {
    NewsItemStatus.FETCHED: {NewsItemStatus.SUMMARIZED, NewsItemStatus.FAILED},
    NewsItemStatus.SUMMARIZED: {NewsItemStatus.VOICED, NewsItemStatus.FAILED},
    NewsItemStatus.VOICED: {NewsItemStatus.READY, NewsItemStatus.FAILED},
    NewsItemStatus.READY: set(),
    NewsItemStatus.FAILED: set(),
}


class NewsItemRepository:
    """Async repository for news_items workflow and play_count."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_from_fetch(self, fetch: NewsFetchInput) -> NewsItem:
        item = NewsItem(
            source_url=fetch.source_url,
            content_hash=fetch.content_hash,
            status=NewsItemStatus.FETCHED,
        )
        self._session.add(item)
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def get_by_id(self, item_id: int) -> NewsItem | None:
        return await self._session.get(NewsItem, item_id)

    async def get_by_source_url(self, source_url: str) -> NewsItem | None:
        result = await self._session.execute(
            select(NewsItem).where(NewsItem.source_url == source_url)
        )
        return result.scalar_one_or_none()

    async def get_by_content_hash(self, content_hash: str) -> NewsItem | None:
        result = await self._session.execute(
            select(NewsItem).where(NewsItem.content_hash == content_hash)
        )
        return result.scalar_one_or_none()

    async def update_summary(self, item_id: int, summary_ru: str) -> NewsItem:
        item = await self._require_item(item_id)
        self._assert_transition(item.status, NewsItemStatus.SUMMARIZED)
        item.summary_ru = summary_ru
        item.status = NewsItemStatus.SUMMARIZED
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def update_audio(self, item_id: int, audio_url: str) -> NewsItem:
        item = await self._require_item(item_id)
        self._assert_transition(item.status, NewsItemStatus.VOICED)
        item.audio_url = audio_url
        item.status = NewsItemStatus.VOICED
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def mark_ready(self, item_id: int) -> NewsItem:
        item = await self._require_item(item_id)
        self._assert_transition(item.status, NewsItemStatus.READY)
        item.status = NewsItemStatus.READY
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def mark_failed(self, item_id: int) -> NewsItem:
        item = await self._require_item(item_id)
        self._assert_transition(item.status, NewsItemStatus.FAILED)
        item.status = NewsItemStatus.FAILED
        await self._session.flush()
        await self._session.refresh(item)
        return item

    async def increment_play_count(
        self,
        item_id: int,
        *,
        played_at: datetime | None = None,
    ) -> NewsItem:
        """Increment play_count once per air slot (caller invokes after fan-out)."""
        item = await self._require_item(item_id)
        if item.status != NewsItemStatus.READY:
            raise InvalidNewsStatusTransition(
                f"Cannot increment play_count for item {item_id} in status {item.status.value}"
            )

        when = played_at or datetime.now(UTC)
        result = await self._session.execute(
            update(NewsItem)
            .where(NewsItem.id == item_id, NewsItem.status == NewsItemStatus.READY)
            .values(
                play_count=NewsItem.play_count + 1,
                last_played_at=when,
            )
            .returning(NewsItem)
        )
        updated = result.scalar_one()
        await self._session.flush()
        await self._session.refresh(updated)
        return updated

    async def _require_item(self, item_id: int) -> NewsItem:
        item = await self.get_by_id(item_id)
        if item is None:
            raise LookupError(f"News item {item_id} not found")
        return item

    @staticmethod
    def _assert_transition(current: NewsItemStatus, target: NewsItemStatus) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidNewsStatusTransition(
                f"Cannot transition from {current.value} to {target.value}"
            )
