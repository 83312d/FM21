"""RSS ingest cron worker — fetch enabled sources every 10 minutes (U16)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass, field

import httpx

from services.db.session import async_session_factory
from services.news.db.repository import NewsItemRepository
from services.news.fetcher.dedup import IngestResult, ingest_article
from services.news.fetcher.rss import DEFAULT_TIMEOUT_SEC, fetch_feed, resolve_entry_body
from services.news.sources_loader import NewsSource, SourcesRegistry, load_sources

logger = logging.getLogger(__name__)


@dataclass
class FetchStats:
    created: int = 0
    skipped_url: int = 0
    skipped_hash: int = 0
    skipped_conflict: int = 0
    skipped_empty_body: int = 0
    entry_errors: int = 0
    source_errors: int = 0

    def record(self, result: IngestResult) -> None:
        if result is IngestResult.CREATED:
            self.created += 1
        elif result is IngestResult.SKIPPED_URL:
            self.skipped_url += 1
        elif result is IngestResult.SKIPPED_HASH:
            self.skipped_hash += 1
        elif result is IngestResult.SKIPPED_CONFLICT:
            self.skipped_conflict += 1
        elif result is IngestResult.SKIPPED_EMPTY_BODY:
            self.skipped_empty_body += 1


@dataclass
class NewsFetchWorker:
    registry: SourcesRegistry
    session_factory: object = field(default=async_session_factory)
    timeout_sec: float = DEFAULT_TIMEOUT_SEC
    _stats: FetchStats = field(default_factory=FetchStats)

    @property
    def stats(self) -> FetchStats:
        return self._stats

    async def process_source(
        self,
        source: NewsSource,
        *,
        client: httpx.AsyncClient,
        feed_body: str | None = None,
    ) -> None:
        entries = await fetch_feed(source.url, client=client, feed_body=feed_body)
        for entry in entries:
            try:
                body_text = await resolve_entry_body(entry, client=client)
                async with self.session_factory()() as session:
                    repo = NewsItemRepository(session)
                    result = await ingest_article(
                        repo,
                        session,
                        source_url=entry.source_url,
                        body_text=body_text,
                    )
                    self._stats.record(result)
                    if result is IngestResult.CREATED:
                        logger.info("Ingested %s from %s", entry.source_url, source.id)
            except Exception:
                self._stats.entry_errors += 1
                logger.exception("Failed to ingest entry %s from %s", entry.source_url, source.id)

    async def run_once(self, *, feed_bodies: dict[str, str] | None = None) -> FetchStats:
        self._stats = FetchStats()
        timeout = httpx.Timeout(self.timeout_sec)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for source in self.registry.enabled_sources:
                try:
                    await self.process_source(
                        source,
                        client=client,
                        feed_body=(feed_bodies or {}).get(source.id),
                    )
                except Exception:
                    self._stats.source_errors += 1
                    logger.exception("Failed to ingest source %s (%s)", source.id, source.url)

        logger.info(
            "News fetch complete: created=%s skipped_url=%s skipped_hash=%s errors=%s",
            self._stats.created,
            self._stats.skipped_url,
            self._stats.skipped_hash,
            self._stats.source_errors,
        )
        return self._stats


def create_worker() -> NewsFetchWorker:
    return NewsFetchWorker(registry=load_sources())


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="FM21 RSS news fetch worker (U16)")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single fetch cycle and exit (cron entrypoint)",
    )
    args = parser.parse_args()

    worker = create_worker()
    if args.once:
        await worker.run_once()
        return

    interval_sec = int(os.environ.get("NEWS_FETCH_INTERVAL_SEC", "600"))
    logger.info("News fetch worker started (interval=%ss)", interval_sec)
    while True:
        try:
            await worker.run_once()
        except Exception:
            logger.exception("News fetch worker tick failed")
        await asyncio.sleep(interval_sec)


if __name__ == "__main__":
    asyncio.run(main())
