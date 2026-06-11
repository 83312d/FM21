"""GigaChat summarizer worker — RU 150–250 word radio copy (U17)."""

from __future__ import annotations

import argparse
import asyncio
import enum
import logging
import os
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select

from services.db.models import NewsItem, NewsItemStatus
from services.db.session import async_session_factory
from services.news.db.repository import NewsItemRepository
from services.news.fetcher.rss import DEFAULT_TIMEOUT_SEC, fetch_article_body
from services.news.http import http_verify_ssl
from services.news.summarizer.gigachat_client import (
    SummarizerClient,
    create_summarizer_client,
)
from services.news.summarizer.validate import is_valid_word_count

logger = logging.getLogger(__name__)


class SummarizeResult(str, enum.Enum):
    SUMMARIZED = "summarized"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class SummarizeStats:
    summarized: int = 0
    skipped: int = 0
    failed: int = 0
    errors: int = 0

    def record(self, result: SummarizeResult) -> None:
        if result is SummarizeResult.SUMMARIZED:
            self.summarized += 1
        elif result is SummarizeResult.SKIPPED:
            self.skipped += 1
        elif result is SummarizeResult.FAILED:
            self.failed += 1


async def generate_summary(
    source_text: str,
    client: SummarizerClient,
) -> str | None:
    """Call GigaChat with one retry when word count is out of range."""
    first = await client.summarize(source_text, tightened=False)
    if is_valid_word_count(first):
        return first

    second = await client.summarize(source_text, tightened=True)
    if is_valid_word_count(second):
        return second

    return None


async def summarize_news_item(
    repo: NewsItemRepository,
    item_id: int,
    source_text: str,
    client: SummarizerClient,
) -> SummarizeResult:
    """Summarize one fetched row; idempotent on already-summarized items."""
    item = await repo.get_by_id(item_id)
    if item is None:
        raise LookupError(f"News item {item_id} not found")

    if item.status != NewsItemStatus.FETCHED:
        return SummarizeResult.SKIPPED

    summary = await generate_summary(source_text, client)
    if summary is None:
        await repo.mark_failed(item_id)
        return SummarizeResult.FAILED

    await repo.update_summary(item_id, summary)
    return SummarizeResult.SUMMARIZED


async def _list_fetched_items(session) -> list[NewsItem]:
    result = await session.execute(
        select(NewsItem)
        .where(NewsItem.status == NewsItemStatus.FETCHED)
        .order_by(NewsItem.id)
    )
    return list(result.scalars().all())


@dataclass
class NewsSummarizeWorker:
    session_factory: object = field(default=async_session_factory)
    timeout_sec: float = DEFAULT_TIMEOUT_SEC
    _stats: SummarizeStats = field(default_factory=SummarizeStats)

    @property
    def stats(self) -> SummarizeStats:
        return self._stats

    async def run_once(self, client: SummarizerClient) -> SummarizeStats:
        self._stats = SummarizeStats()
        timeout = httpx.Timeout(self.timeout_sec)

        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, verify=http_verify_ssl()
        ) as http_client:
            async with self.session_factory()() as session:
                repo = NewsItemRepository(session)
                items = await _list_fetched_items(session)

                for item in items:
                    try:
                        source_text = await fetch_article_body(
                            item.source_url,
                            client=http_client,
                        )
                        if not source_text.strip():
                            await repo.mark_failed(item.id)
                            self._stats.record(SummarizeResult.FAILED)
                            continue

                        result = await summarize_news_item(
                            repo,
                            item.id,
                            source_text,
                            client,
                        )
                        self._stats.record(result)
                        if result is SummarizeResult.SUMMARIZED:
                            logger.info("Summarized news item %s", item.id)
                    except Exception:
                        self._stats.errors += 1
                        logger.exception("Failed to summarize news item %s", item.id)

                await session.commit()

        logger.info(
            "News summarize complete: summarized=%s skipped=%s failed=%s errors=%s",
            self._stats.summarized,
            self._stats.skipped,
            self._stats.failed,
            self._stats.errors,
        )
        return self._stats


def create_worker() -> NewsSummarizeWorker:
    return NewsSummarizeWorker()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="FM21 news summarizer worker (U17)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single summarize cycle and exit (cron entrypoint)",
    )
    args = parser.parse_args()

    worker = create_worker()
    client = create_summarizer_client()

    if args.once:
        await worker.run_once(client)
        return

    interval_sec = int(os.environ.get("NEWS_SUMMARIZE_INTERVAL_SEC", "300"))
    logger.info("News summarize worker started (interval=%ss)", interval_sec)
    while True:
        try:
            await worker.run_once(client)
        except Exception:
            logger.exception("News summarize worker tick failed")
        await asyncio.sleep(interval_sec)


if __name__ == "__main__":
    asyncio.run(main())
