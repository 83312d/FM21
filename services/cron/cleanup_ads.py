"""Delete terminal ads rows and on-disk MP3 files (TZ §9 cache-cleanup)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select

from services.db.models import Ad, AdStatus
from services.db.session import async_session_factory

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = (AdStatus.PLAYED, AdStatus.REJECTED)
DEFAULT_ADS_DIR = Path(os.environ.get("ADS_DIR", "/data/ads"))


def _audio_path_from_url(audio_url: str, ads_dir: Path) -> Path | None:
    if not audio_url.startswith("file://"):
        return None
    path = Path(audio_url.removeprefix("file://"))
    try:
        path.resolve().relative_to(ads_dir.resolve())
    except ValueError:
        return None
    return path


@dataclass
class AdsCleanupResult:
    rows_deleted: int
    files_deleted: int


async def cleanup_expired_ads(
    session_factory: object = async_session_factory,
    *,
    ads_dir: Path | None = None,
) -> tuple[int, int]:
    target_dir = ads_dir or DEFAULT_ADS_DIR
    files_deleted = 0

    async with session_factory()() as session:
        result = await session.execute(
            select(Ad).where(Ad.status.in_(TERMINAL_STATUSES))
        )
        ads = list(result.scalars().all())
        for ad in ads:
            path = _audio_path_from_url(ad.audio_url, target_dir)
            if path is not None and path.exists():
                path.unlink()
                files_deleted += 1

        delete_result = await session.execute(
            delete(Ad).where(Ad.status.in_(TERMINAL_STATUSES))
        )
        await session.commit()
        rows_deleted = delete_result.rowcount or 0

    logger.info(
        "Expired ads cleanup complete: rows=%s files=%s",
        rows_deleted,
        files_deleted,
    )
    return rows_deleted, files_deleted


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="FM21 expired ads cleanup (U32)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cleanup cycle and exit",
    )
    args = parser.parse_args()

    if args.once:
        await cleanup_expired_ads()
        return

    from services.cron.timing import CRON_CACHE_CLEANUP, seconds_until_next_cron  # noqa: PLC0415

    logger.info("Ads cleanup worker started (schedule=%s UTC)", CRON_CACHE_CLEANUP)
    while True:
        sleep_sec = seconds_until_next_cron(CRON_CACHE_CLEANUP)
        logger.info("Next ads cleanup in %.0f seconds", sleep_sec)
        await asyncio.sleep(sleep_sec)
        try:
            await cleanup_expired_ads()
        except Exception:
            logger.exception("Ads cleanup tick failed")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
