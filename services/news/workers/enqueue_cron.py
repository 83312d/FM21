"""News enqueue cron — NEWS_PAIR fan-out at :00,:15,:30,:45 UTC (U21)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

import redis

from services.db.models import NewsItemStatus
from services.db.session import async_session_factory
from services.injector.fanout import load_active_cities
from services.injector.queue import QueueClient
from services.news.db.repository import NewsItemRepository
from services.news.enqueue import (
    NewsEnqueueFailure,
    NewsEnqueueResult,
    build_news_pair_payload,
    enqueue_news_pair,
    record_air_slot,
    should_skip_for_slip,
)
from services.news.pipeline import get_pinned_item_id
from services.news.play_count import redis_client_from_env
from services.news.slot_clock import (
    current_enqueue_slot,
    is_enqueue_minute,
    seconds_until_next_enqueue,
    slot_iso,
)

logger = logging.getLogger(__name__)


@dataclass
class EnqueueStats:
    cities: int = 0
    enqueued: bool = False
    skipped_slip: bool = False
    skipped_no_pin: bool = False
    skipped_not_ready: bool = False
    skipped_injector: bool = False
    item_id: int | None = None


@dataclass
class NewsEnqueueWorker:
    cities: list[str]
    session_factory: object = field(default=async_session_factory)
    redis_factory: object = field(default=redis_client_from_env)
    max_pending_ads: int = field(
        default_factory=lambda: int(os.environ.get("MAX_PENDING_ADS_PER_CITY", "5"))
    )
    _stats: EnqueueStats = field(default_factory=EnqueueStats)

    @property
    def stats(self) -> EnqueueStats:
        return self._stats

    async def run_once(
        self,
        *,
        now: datetime | None = None,
        redis_client: redis.Redis | None = None,
    ) -> EnqueueStats:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if not is_enqueue_minute(current):
            logger.warning(
                "Enqueue run at non-cron minute %s (expected :00,:15,:30,:45)",
                current.strftime("%H:%M"),
            )

        slot = current_enqueue_slot(current)
        slot_key = slot_iso(slot)
        redis_conn = redis_client or self.redis_factory()
        redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
        queue = QueueClient(redis_url, self.max_pending_ads)

        self._stats = EnqueueStats(cities=len(self.cities))

        skip_slip, slip_city = should_skip_for_slip(
            redis_conn,
            queue,
            self.cities,
            slot=slot,
            now=current,
        )
        if skip_slip:
            self._stats.skipped_slip = True
            logger.warning(
                "Skipping news slot %s — slip > %ss for city %s",
                slot_key,
                os.environ.get("NEWS_MAX_SLIP_SEC", "600"),
                slip_city,
            )
            return self._stats

        pinned: dict[str, int] = {}
        for city in self.cities:
            item_id = get_pinned_item_id(redis_conn, city, slot_key)
            if item_id is None:
                self._stats.skipped_no_pin = True
                logger.warning("No slot pin for %s slot %s — skip enqueue", city, slot_key)
                return self._stats
            pinned[city] = item_id

        unique_ids = set(pinned.values())
        if len(unique_ids) != 1:
            logger.warning(
                "Mismatched slot pins for %s: %s — using first city pin",
                slot_key,
                pinned,
            )
        item_id = pinned[self.cities[0]]

        async with self.session_factory()() as session:
            repo = NewsItemRepository(session)
            item = await repo.get_by_id(item_id)
            if item is None or item.status != NewsItemStatus.READY or not item.audio_url:
                self._stats.skipped_not_ready = True
                logger.warning(
                    "Pinned item %s not ready for slot %s (status=%s)",
                    item_id,
                    slot_key,
                    getattr(item, "status", None),
                )
                return self._stats

            payload = build_news_pair_payload(item)
            result = await enqueue_news_pair(payload)
            if isinstance(result, NewsEnqueueFailure):
                self._stats.skipped_injector = True
                logger.error(
                    "Injector rejected NEWS_PAIR for slot %s: %s (city=%s)",
                    slot_key,
                    result.message,
                    result.city_tag,
                )
                return self._stats

            if not isinstance(result, NewsEnqueueResult):
                self._stats.skipped_injector = True
                return self._stats

            await record_air_slot(repo, item, redis_conn, played_at=slot)
            await session.commit()

            self._stats.enqueued = True
            self._stats.item_id = item_id
            logger.info(
                "NEWS_PAIR enqueued slot %s item %s cities=%s queue_ids=%s",
                slot_key,
                item_id,
                result.city_tags,
                result.id,
            )

        return self._stats


def create_worker() -> NewsEnqueueWorker:
    cities_path = os.environ.get("CITIES_YAML_PATH", "broadcast/liquidsoap/cities.yaml")
    return NewsEnqueueWorker(cities=load_active_cities(cities_path))


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="FM21 news enqueue worker (U21)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single enqueue cycle and exit (cron entrypoint)",
    )
    args = parser.parse_args()

    worker = create_worker()
    if args.once:
        await worker.run_once()
        return

    logger.info("News enqueue worker started (schedule=0,15,30,45 * * * * UTC)")
    while True:
        sleep_sec = seconds_until_next_enqueue()
        logger.info("Next enqueue tick in %.0f seconds", sleep_sec)
        await asyncio.sleep(sleep_sec)
        try:
            await worker.run_once()
        except Exception:
            logger.exception("News enqueue worker tick failed")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
