"""News item selection for air slots — ready items, play cap, rotation (U19)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis

from services.db.models import NewsItem, NewsItemStatus
from services.news.db.repository import NewsItemRepository
from services.news.play_count import MAX_PLAYS_PER_24H, get_played_count, is_at_play_cap


async def list_ready_ordered(session: AsyncSession) -> list[NewsItem]:
    """Ready items rotated by least-recently played (NULLS FIRST)."""
    result = await session.execute(
        select(NewsItem)
        .where(NewsItem.status == NewsItemStatus.READY)
        .order_by(NewsItem.last_played_at.asc().nulls_first(), NewsItem.id)
    )
    return list(result.scalars().all())


def _is_under_play_cap(item: NewsItem, redis_client: redis.Redis, *, cap: int) -> bool:
    if item.play_count >= cap:
        return False
    if item.content_hash and is_at_play_cap(redis_client, item.content_hash, cap=cap):
        return False
    return True


async def select_news_item(
    repo: NewsItemRepository,
    session: AsyncSession,
    redis_client: redis.Redis,
    *,
    max_plays: int = MAX_PLAYS_PER_24H,
) -> NewsItem | None:
    """Pick the next news item for an air slot (AE3).

  Prefer ``ready`` items with ``play_count < max_plays`` and Redis mirror below cap,
  ordered by ``last_played_at ASC NULLS FIRST``. When every ready item is at cap,
  fall back to the same rotation order so cached audio can air without new TTS.
    """
    _ = repo  # selection uses session queries; repo kept for U20/U21 call sites
    candidates = await list_ready_ordered(session)
    if not candidates:
        return None

    under_cap = [item for item in candidates if _is_under_play_cap(item, redis_client, cap=max_plays)]
    if under_cap:
        return under_cap[0]

    return candidates[0]


def effective_play_count(item: NewsItem, redis_client: redis.Redis) -> int:
    """Max of PostgreSQL and Redis play counts for diagnostics/tests."""
    redis_count = get_played_count(redis_client, item.content_hash) if item.content_hash else 0
    return max(item.play_count, redis_count)
