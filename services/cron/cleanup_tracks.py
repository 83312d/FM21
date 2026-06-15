"""Delete expired Yandex stream URLs from tracks_cache (TZ §9 cache-cleanup)."""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import delete

from services.db.models import TrackCache
from services.db.session import async_session_factory

logger = logging.getLogger(__name__)


async def cleanup_expired_tracks(
    session_factory: object = async_session_factory,
    *,
    now: datetime | None = None,
) -> int:
    cutoff = now or datetime.now(UTC)
    async with session_factory()() as session:
        result = await session.execute(
            delete(TrackCache).where(TrackCache.stream_url_expires < cutoff)
        )
        await session.commit()
        deleted = result.rowcount or 0
    logger.info("Expired tracks_cache rows deleted: %s", deleted)
    return deleted


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="FM21 tracks_cache cleanup (U32)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cleanup cycle and exit",
    )
    args = parser.parse_args()

    if args.once:
        await cleanup_expired_tracks()
        return

    from services.cron.timing import CRON_CACHE_CLEANUP, seconds_until_next_cron  # noqa: PLC0415

    logger.info("Tracks cleanup worker started (schedule=%s UTC)", CRON_CACHE_CLEANUP)
    while True:
        sleep_sec = seconds_until_next_cron(CRON_CACHE_CLEANUP)
        logger.info("Next tracks cleanup in %.0f seconds", sleep_sec)
        await asyncio.sleep(sleep_sec)
        try:
            await cleanup_expired_tracks()
        except Exception:
            logger.exception("Tracks cleanup tick failed")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
