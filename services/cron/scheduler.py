"""FM21 maintenance cron scheduler — cache cleanup, news reset (U32, TZ §9)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from services.cron.cleanup_ads import cleanup_expired_ads
from services.cron.cleanup_tracks import cleanup_expired_tracks
from services.cron.news_cache_reset import NewsCacheResetWorker
from services.cron.timing import (
    CRON_CACHE_CLEANUP,
    CRON_NEWS_CACHE_RESET,
    CRON_PLAYLIST_REFRESH,
    is_cron_due,
    seconds_until_next_cron,
)
from services.db.session import async_session_factory
from services.news.play_count import redis_client_from_env

logger = logging.getLogger(__name__)

# music-worker fills the buffer every MUSIC_BUFFER_POLL_INTERVAL_SEC (default 15s).
# Hourly playlist-refresh from TZ §9 is redundant in containerized deploy — documented here.
PLAYLIST_REFRESH_DELEGATED_TO = "music-worker"


async def run_cache_cleanup(
    session_factory: object = async_session_factory,
    *,
    ads_dir: Path | None = None,
    now: datetime | None = None,
) -> tuple[int, int, int]:
    tracks_deleted = await cleanup_expired_tracks(session_factory, now=now)
    ads_deleted, files_deleted = await cleanup_expired_ads(
        session_factory,
        ads_dir=ads_dir,
    )
    return tracks_deleted, ads_deleted, files_deleted


@dataclass
class CronScheduler:
    session_factory: object = field(default=async_session_factory)
    redis_factory: object = field(default=redis_client_from_env)
    ads_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("ADS_DIR", "/data/ads"))
    )

    async def run_due_jobs(self, *, now: datetime | None = None) -> dict[str, dict[str, int]]:
        current = now or datetime.now(UTC)
        results: dict[str, dict[str, int]] = {}

        if is_cron_due(CRON_NEWS_CACHE_RESET, now=current):
            worker = NewsCacheResetWorker(
                session_factory=self.session_factory,
                redis_factory=self.redis_factory,
            )
            pg_reset, redis_deleted = await worker.run_once()
            results["news-cache-reset"] = {
                "pg_reset": pg_reset,
                "redis_deleted": redis_deleted,
            }

        if is_cron_due(CRON_CACHE_CLEANUP, now=current):
            tracks_deleted, ads_deleted, files_deleted = await run_cache_cleanup(
                self.session_factory,
                ads_dir=self.ads_dir,
                now=current,
            )
            results["cache-cleanup"] = {
                "tracks_deleted": tracks_deleted,
                "ads_deleted": ads_deleted,
                "files_deleted": files_deleted,
            }

        if is_cron_due(CRON_PLAYLIST_REFRESH, now=current):
            logger.info(
                "playlist-refresh skipped — delegated to %s (continuous buffer fill)",
                PLAYLIST_REFRESH_DELEGATED_TO,
            )
            results["playlist-refresh"] = {"skipped": 1}

        return results

    async def run_once(self) -> dict[str, dict[str, int]]:
        """Run all maintenance jobs regardless of schedule (manual dev testing)."""
        tracks_deleted, ads_deleted, files_deleted = await run_cache_cleanup(
            self.session_factory,
            ads_dir=self.ads_dir,
        )
        worker = NewsCacheResetWorker(
            session_factory=self.session_factory,
            redis_factory=self.redis_factory,
        )
        pg_reset, redis_deleted = await worker.run_once()
        return {
            "cache-cleanup": {
                "tracks_deleted": tracks_deleted,
                "ads_deleted": ads_deleted,
                "files_deleted": files_deleted,
            },
            "news-cache-reset": {
                "pg_reset": pg_reset,
                "redis_deleted": redis_deleted,
            },
            "playlist-refresh": {"skipped": 1},
        }

    def _next_sleep_sec(self, *, now: datetime | None = None) -> float:
        current = now or datetime.now(UTC)
        candidates = [
            seconds_until_next_cron(CRON_NEWS_CACHE_RESET, now=current),
            seconds_until_next_cron(CRON_CACHE_CLEANUP, now=current),
            seconds_until_next_cron(CRON_PLAYLIST_REFRESH, now=current),
        ]
        return min(candidates)

    async def run_forever(self) -> None:
        logger.info(
            "Cron scheduler started (cache-cleanup=%s, news-cache-reset=%s, playlist-refresh=delegated)",
            CRON_CACHE_CLEANUP,
            CRON_NEWS_CACHE_RESET,
        )
        while True:
            sleep_sec = self._next_sleep_sec()
            logger.info("Next cron check in %.0f seconds", sleep_sec)
            await asyncio.sleep(sleep_sec)
            try:
                results = await self.run_due_jobs()
                if results:
                    logger.info("Cron jobs fired: %s", results)
            except Exception:
                logger.exception("Cron scheduler tick failed")
            await asyncio.sleep(1)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="FM21 maintenance cron scheduler (U32)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run all maintenance jobs once and exit (ignores schedule)",
    )
    args = parser.parse_args()

    scheduler = CronScheduler()
    if args.once:
        results = await scheduler.run_once()
        logger.info("Manual cron run complete: %s", results)
        return

    await scheduler.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
