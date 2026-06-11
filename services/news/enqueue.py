"""NEWS_PAIR injector client, slip guard, and play_count bookkeeping (U21)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import redis

from services.db.models import NewsItem, NewsItemStatus
from services.injector.fanout import TYPE_PRIORITIES
from services.injector.queue import QueueClient
from services.news.audio_probe import AudioProbeError, probe_duration_sec
from services.news.db.repository import NewsItemRepository
from services.news.play_count import increment_played_count
from services.news.storage import get_news_storage

logger = logging.getLogger(__name__)

INJECTOR_URL = os.environ.get("INJECTOR_URL", "http://injector:8080")
CURRENT_KEY_PREFIX = "fm21:current:"
MAX_SLIP_SEC = int(os.environ.get("NEWS_MAX_SLIP_SEC", "600"))
NEWS_PAIR_PRIORITY = TYPE_PRIORITIES["NEWS_PAIR"]
DEFAULT_NEWS_DURATION_SEC = int(os.environ.get("NEWS_DEFAULT_DURATION_SEC", "90"))


def _internal_token() -> str:
    return os.environ.get("INTERNAL_ENQUEUE_TOKEN", "")


@dataclass(frozen=True)
class NewsEnqueueResult:
    id: str
    city_tags: list[str]


@dataclass(frozen=True)
class NewsEnqueueFailure:
    status_code: int
    message: str
    city_tag: str | None = None


def resolve_duration_sec(audio_url: str, *, default: int = DEFAULT_NEWS_DURATION_SEC) -> int:
    if audio_url.startswith("file://"):
        path = Path(audio_url.removeprefix("file://"))
        try:
            return max(1, int(round(probe_duration_sec(path))))
        except AudioProbeError:
            pass
    return default


def build_news_pair_payload(
    item: NewsItem,
    *,
    duration_sec: int | None = None,
    stinger_uri: str | None = None,
) -> dict:
    if not item.audio_url:
        raise ValueError(f"News item {item.id} has no audio_url")

    storage = get_news_storage()
    resolved_duration = duration_sec or resolve_duration_sec(item.audio_url)
    title = (item.summary_ru or "Новости").strip()
    if len(title) > 200:
        title = title[:197] + "..."

    return {
        "type": "NEWS_PAIR",
        "uri": item.audio_url,
        "city_tag": "all",
        "meta": {
            "title": title,
            "duration_sec": resolved_duration,
            "stinger_uri": stinger_uri or storage.stinger_uri(),
        },
    }


def _current_block_remaining_sec(redis_client: redis.Redis, city: str, now: datetime) -> float:
    data = redis_client.hgetall(f"{CURRENT_KEY_PREFIX}{city}")
    if not data:
        return 0.0

    started_raw = data.get("started_at")
    duration_raw = data.get("duration_sec")
    if not started_raw or duration_raw is None:
        return 0.0

    try:
        started = datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
        duration = float(duration_raw)
    except (ValueError, TypeError):
        return 0.0

    elapsed = (now.astimezone(UTC) - started.astimezone(UTC)).total_seconds()
    return max(0.0, duration - elapsed)


def _pending_higher_priority_duration_sec(queue_client: QueueClient, city: str) -> float:
    total = 0.0
    for item in queue_client.list_items(city):
        priority = int(item.get("priority", 0))
        if priority > NEWS_PAIR_PRIORITY:
            meta = item.get("meta") or {}
            total += float(meta.get("duration_sec", 0))
    return total


def estimate_slip_sec(
    redis_client: redis.Redis,
    queue_client: QueueClient,
    city: str,
    *,
    slot: datetime,
    now: datetime,
) -> float:
    """Seconds news would slip past ``slot`` given current block + AD backlog."""
    now_utc = now.astimezone(UTC)
    slot_utc = slot.astimezone(UTC)
    past_slot = max(0.0, (now_utc - slot_utc).total_seconds())
    backlog = _current_block_remaining_sec(redis_client, city, now_utc)
    backlog += _pending_higher_priority_duration_sec(queue_client, city)
    return past_slot + backlog


def should_skip_for_slip(
    redis_client: redis.Redis,
    queue_client: QueueClient,
    cities: list[str],
    *,
    slot: datetime,
    now: datetime,
    max_slip_sec: int = MAX_SLIP_SEC,
) -> tuple[bool, str | None]:
    worst_city: str | None = None
    worst_slip = 0.0
    for city in cities:
        slip = estimate_slip_sec(redis_client, queue_client, city, slot=slot, now=now)
        if slip > worst_slip:
            worst_slip = slip
            worst_city = city

    if worst_slip > max_slip_sec:
        return True, worst_city
    return False, None


async def enqueue_news_pair(payload: dict) -> NewsEnqueueResult | NewsEnqueueFailure:
    headers = {"X-FM21-Internal-Token": _internal_token()}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{INJECTOR_URL}/internal/enqueue",
            json=payload,
            headers=headers,
        )

    if response.status_code == 201:
        body = response.json()
        return NewsEnqueueResult(id=body["id"], city_tags=body.get("city_tags", []))

    message = "Failed to enqueue NEWS_PAIR."
    city: str | None = None
    try:
        detail = response.json().get("detail")
        if isinstance(detail, dict):
            message = detail.get("message", message)
            city = detail.get("city_tag")
        elif isinstance(detail, str):
            message = detail
    except (ValueError, AttributeError, json.JSONDecodeError):
        pass

    return NewsEnqueueFailure(
        status_code=response.status_code,
        message=message,
        city_tag=city,
    )


async def record_air_slot(
    repo: NewsItemRepository,
    item: NewsItem,
    redis_client: redis.Redis,
    *,
    played_at: datetime,
) -> None:
    """Increment PostgreSQL play_count once and mirror Redis (ADR-007)."""
    if item.status != NewsItemStatus.READY:
        raise ValueError(f"Cannot record air for item {item.id} in status {item.status.value}")

    await repo.increment_play_count(item.id, played_at=played_at)
    if item.content_hash:
        increment_played_count(redis_client, item.content_hash)
