"""Midnight UTC play_count reset — PostgreSQL source of truth + Redis mirror (U19)."""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from services.db.models import NewsItem
from services.db.session import async_session_factory
from services.news.play_count import clear_played_keys, redis_client_from_env

logger = logging.getLogger(__name__)


def seconds_until_next_midnight_utc(*, now: datetime | None = None) -> float:
    current = now or datetime.now(UTC)
    today_midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
    next_midnight = today_midnight + timedelta(days=1)
    return max(0.0, (next_midnight - current).total_seconds())


async def reset_postgres_play_counts(session_factory: object = async_session_factory) -> int:
    async with session_factory()() as session:
        result = await session.execute(
            update(NewsItem)
            .where(NewsItem.play_count > 0)
            .values(play_count=0, last_played_at=None)
        )
        await session.commit()
        return result.rowcount or 0


@dataclass
class PlayCountResetWorker:
    session_factory: object = field(default=async_session_factory)
    redis_factory: object = field(default=redis_client_from_env)

    async def run_once(self) -> tuple[int, int]:
        pg_reset = await reset_postgres_play_counts(self.session_factory)
        redis_deleted = clear_played_keys(self.redis_factory())
        logger.info(
            "Play count reset complete: pg_rows=%s redis_keys_deleted=%s",
            pg_reset,
            redis_deleted,
        )
        return pg_reset, redis_deleted


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="FM21 news play_count midnight reset (U19)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single reset cycle and exit (cron entrypoint)",
    )
    args = parser.parse_args()

    worker = PlayCountResetWorker()
    if args.once:
        await worker.run_once()
        return

    logger.info("Play count reset worker started (schedule=0 0 * * * UTC)")
    while True:
        sleep_sec = seconds_until_next_midnight_utc()
        logger.info("Next reset in %.0f seconds", sleep_sec)
        await asyncio.sleep(sleep_sec)
        try:
            await worker.run_once()
        except Exception:
            logger.exception("Play count reset tick failed")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
