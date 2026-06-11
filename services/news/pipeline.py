"""News materialize pipeline — select, summarize, TTS, slot pin (U20)."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass

import httpx
import redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.models import NewsItem, NewsItemStatus
from services.news.db.repository import NewsItemRepository
from services.news.fetcher.rss import DEFAULT_TIMEOUT_SEC, fetch_article_body
from services.news.selection import select_news_item
from services.news.summarizer.gigachat_client import SummarizerClient
from services.news.tts.salutespeech import SaluteSpeechTTS
from services.news.workers.summarize import SummarizeResult, summarize_news_item

logger = logging.getLogger(__name__)

SLOT_PIN_PREFIX = "fm21:news:slot:"
SLOT_PIN_TTL_SEC = 30 * 60


class MaterializeResult(str, enum.Enum):
    READY = "ready"
    MATERIALIZED = "materialized"
    FAILED = "failed"
    NO_ITEM = "no_item"


def slot_pin_key(city: str, slot_iso: str) -> str:
    return f"{SLOT_PIN_PREFIX}{city}:{slot_iso}"


def pin_slot_item(
    redis_client: redis.Redis,
    city: str,
    slot_iso: str,
    item_id: int,
) -> None:
    redis_client.set(slot_pin_key(city, slot_iso), str(item_id), ex=SLOT_PIN_TTL_SEC)


def get_pinned_item_id(
    redis_client: redis.Redis,
    city: str,
    slot_iso: str,
) -> int | None:
    raw = redis_client.get(slot_pin_key(city, slot_iso))
    if raw is None:
        return None
    return int(raw)


async def select_for_materialize(
    repo: NewsItemRepository,
    session: AsyncSession,
    redis_client: redis.Redis,
) -> NewsItem | None:
    """Pick an item to pin for the upcoming slot.

    Advance the pipeline first: oldest ``fetched`` or ``summarized`` row gets
    summary/TTS so new stories rotate on air. Fall back to rotation-eligible
    ``ready`` items only when nothing is queued for materialization.
    """
    result = await session.execute(
        select(NewsItem)
        .where(NewsItem.status == NewsItemStatus.FETCHED)
        .order_by(NewsItem.id)
        .limit(1)
    )
    fetched = result.scalar_one_or_none()
    if fetched is not None:
        return fetched

    result = await session.execute(
        select(NewsItem)
        .where(NewsItem.status == NewsItemStatus.SUMMARIZED)
        .order_by(NewsItem.id)
        .limit(1)
    )
    summarized = result.scalar_one_or_none()
    if summarized is not None:
        return summarized

    return await select_news_item(repo, session, redis_client)


async def materialize_news_item(
    repo: NewsItemRepository,
    item_id: int,
    *,
    summarizer_client: SummarizerClient,
    tts_client: SaluteSpeechTTS,
    http_client: httpx.AsyncClient,
) -> MaterializeResult:
    """Run summarize and/or TTS until the item is ``ready`` (idempotent)."""
    item = await repo.get_by_id(item_id)
    if item is None:
        raise LookupError(f"News item {item_id} not found")

    if item.status == NewsItemStatus.READY:
        return MaterializeResult.READY

    if item.status == NewsItemStatus.FETCHED:
        source_text = await fetch_article_body(item.source_url, client=http_client)
        if not source_text.strip():
            await repo.mark_failed(item_id)
            return MaterializeResult.FAILED

        summary_result = await summarize_news_item(
            repo,
            item_id,
            source_text,
            summarizer_client,
        )
        if summary_result is SummarizeResult.FAILED:
            return MaterializeResult.FAILED
        if summary_result is not SummarizeResult.SUMMARIZED:
            return MaterializeResult.FAILED

        item = await repo.get_by_id(item_id)
        if item is None or item.status != NewsItemStatus.SUMMARIZED:
            return MaterializeResult.FAILED

    if item.status == NewsItemStatus.SUMMARIZED:
        await tts_client.voice_news_item(repo, item_id)
        return MaterializeResult.MATERIALIZED

    if item.status == NewsItemStatus.VOICED:
        await repo.mark_ready(item_id)
        return MaterializeResult.MATERIALIZED

    return MaterializeResult.FAILED


@dataclass
class MaterializeStats:
    cities: int = 0
    pinned: int = 0
    ready: int = 0
    materialized: int = 0
    failed: int = 0
    no_item: int = 0

    def record(self, result: MaterializeResult) -> None:
        if result is MaterializeResult.READY:
            self.ready += 1
        elif result is MaterializeResult.MATERIALIZED:
            self.materialized += 1
        elif result is MaterializeResult.FAILED:
            self.failed += 1
        elif result is MaterializeResult.NO_ITEM:
            self.no_item += 1
