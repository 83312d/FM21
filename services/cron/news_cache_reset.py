"""Midnight news play_count reset — thin wrapper over U19 worker (TZ §9)."""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass, field

from services.db.session import async_session_factory
from services.news.play_count import redis_client_from_env
from services.news.workers.play_count_reset import (
    PlayCountResetWorker,
    seconds_until_next_midnight_utc,
)

logger = logging.getLogger(__name__)


@dataclass
class NewsCacheResetWorker:
    session_factory: object = field(default=async_session_factory)
    redis_factory: object = field(default=redis_client_from_env)

    async def run_once(self) -> tuple[int, int]:
        worker = PlayCountResetWorker(
            session_factory=self.session_factory,
            redis_factory=self.redis_factory,
        )
        return await worker.run_once()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="FM21 news cache reset (U32)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single reset cycle and exit",
    )
    args = parser.parse_args()

    worker = NewsCacheResetWorker()
    if args.once:
        await worker.run_once()
        return

    logger.info("News cache reset worker started (schedule=0 0 * * * UTC)")
    while True:
        sleep_sec = seconds_until_next_midnight_utc()
        logger.info("Next news cache reset in %.0f seconds", sleep_sec)
        await asyncio.sleep(sleep_sec)
        try:
            await worker.run_once()
        except Exception:
            logger.exception("News cache reset tick failed")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
