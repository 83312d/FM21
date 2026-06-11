"""News materialize cron — pre-generate summary + audio T−2 min before slot (U20)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import redis

from services.db.session import async_session_factory
from services.injector.fanout import load_active_cities
from services.news.db.repository import NewsItemRepository
from services.news.http import http_verify_ssl
from services.news.pipeline import (
    MaterializeResult,
    MaterializeStats,
    materialize_news_item,
    pin_slot_item,
    select_for_materialize,
)
from services.news.play_count import redis_client_from_env
from services.news.slot_clock import (
    enqueue_slot_for_materialize,
    is_materialize_minute,
    seconds_until_next_materialize,
    slot_iso,
)
from services.news.summarizer.gigachat_client import create_summarizer_client
from services.news.tts.salutespeech import SaluteSpeechTTS
from services.news.fetcher.rss import DEFAULT_TIMEOUT_SEC

logger = logging.getLogger(__name__)


@dataclass
class NewsMaterializeWorker:
    cities: list[str]
    session_factory: object = field(default=async_session_factory)
    redis_factory: object = field(default=redis_client_from_env)
    timeout_sec: float = DEFAULT_TIMEOUT_SEC
    _stats: MaterializeStats = field(default_factory=MaterializeStats)

    @property
    def stats(self) -> MaterializeStats:
        return self._stats

    async def run_once(
        self,
        *,
        now: datetime | None = None,
        summarizer_client: object | None = None,
        tts_client: SaluteSpeechTTS | None = None,
        redis_client: redis.Redis | None = None,
    ) -> MaterializeStats:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if not is_materialize_minute(current):
            logger.warning(
                "Materialize run at non-cron minute %s (expected :02,:17,:32,:47)",
                current.strftime("%H:%M"),
            )

        enqueue_slot = enqueue_slot_for_materialize(current)
        slot_key = slot_iso(enqueue_slot)
        redis_conn = redis_client or self.redis_factory()
        summarizer = summarizer_client or create_summarizer_client()
        tts = tts_client or SaluteSpeechTTS(redis_client=redis_conn)
        self._stats = MaterializeStats(cities=len(self.cities))

        timeout = httpx.Timeout(self.timeout_sec)
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, verify=http_verify_ssl()
        ) as http_client:
            for city in self.cities:
                async with self.session_factory()() as session:
                    repo = NewsItemRepository(session)
                    item = await select_for_materialize(repo, session, redis_conn)
                    if item is None:
                        self._stats.record(MaterializeResult.NO_ITEM)
                        logger.info("No news item to materialize for %s slot %s", city, slot_key)
                        continue

                    pin_slot_item(redis_conn, city, slot_key, item.id)
                    self._stats.pinned += 1

                    result = await materialize_news_item(
                        repo,
                        item.id,
                        summarizer_client=summarizer,
                        tts_client=tts,
                        http_client=http_client,
                    )
                    self._stats.record(result)
                    await session.commit()

                    logger.info(
                        "Materialize %s slot %s item %s -> %s",
                        city,
                        slot_key,
                        item.id,
                        result.value,
                    )

        logger.info(
            "News materialize complete: cities=%s pinned=%s ready=%s materialized=%s failed=%s no_item=%s",
            self._stats.cities,
            self._stats.pinned,
            self._stats.ready,
            self._stats.materialized,
            self._stats.failed,
            self._stats.no_item,
        )
        return self._stats


def create_worker() -> NewsMaterializeWorker:
    cities_path = os.environ.get("CITIES_YAML_PATH", "broadcast/liquidsoap/cities.yaml")
    return NewsMaterializeWorker(cities=load_active_cities(cities_path))


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="FM21 news materialize worker (U20)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single materialize cycle and exit (cron entrypoint)",
    )
    args = parser.parse_args()

    worker = create_worker()
    if args.once:
        await worker.run_once()
        return

    logger.info("News materialize worker started (schedule=2,17,32,47 * * * * UTC)")
    while True:
        sleep_sec = seconds_until_next_materialize()
        logger.info("Next materialize tick in %.0f seconds", sleep_sec)
        await asyncio.sleep(sleep_sec)
        try:
            await worker.run_once()
        except Exception:
            logger.exception("News materialize worker tick failed")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
