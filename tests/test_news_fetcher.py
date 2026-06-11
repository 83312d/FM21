"""News RSS fetcher tests (U16)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.migrate import run_migrations
from services.db.models import NewsItem, NewsItemStatus
from services.db.session import async_session_factory, get_engine, reset_engine
from services.news.fetcher.dedup import IngestResult, ingest_article
from services.news.fetcher.normalize import content_hash, normalize_url
from services.news.fetcher.rss import fetch_feed, resolve_entry_body
from services.news.sources_loader import NewsSource, SourcesRegistry, load_sources
from services.news.workers.fetch_cron import NewsFetchWorker


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "feeds"


def _read_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _test_registry() -> SourcesRegistry:
    return SourcesRegistry(
        version=1,
        sources=(
            NewsSource(
                id="test",
                name="Test Feed",
                url="https://example.com/feed.xml",
                enabled=True,
                weight=1,
            ),
        ),
    )


@pytest.fixture(autouse=True)
def _reset_engine():
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
async def migrated_db():
    await run_migrations()
    yield
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE news_items RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db_session(migrated_db) -> AsyncSession:
    async with async_session_factory()() as session:
        yield session


def test_load_sources_reads_approved_feeds():
    registry = load_sources()
    assert registry.version == 1
    assert {source.id for source in registry.sources} == {"habr", "3dnews"}
    assert all(source.enabled for source in registry.sources)
    assert all(source.weight == 1 for source in registry.sources)


def test_normalize_url_strips_utm_params():
    raw = "https://Example.com/path?utm_source=rss&utm_campaign=test&keep=1#section"
    assert normalize_url(raw) == "https://example.com/path?keep=1"


@pytest.mark.asyncio
async def test_fixture_rss_creates_rows(migrated_db, db_session: AsyncSession):
    worker = NewsFetchWorker(
        registry=_test_registry(),
        session_factory=async_session_factory,
    )
    stats = await worker.run_once(
        feed_bodies={"test": _read_fixture("sample.xml")},
    )

    assert stats.created == 2
    assert stats.source_errors == 0

    result = await db_session.execute(
        select(NewsItem).where(NewsItem.status == NewsItemStatus.FETCHED)
    )
    items = result.scalars().all()
    assert len(items) == 2
    urls = {item.source_url for item in items}
    assert urls == {
        "https://example.com/news/first-article",
        "https://example.com/news/second-article",
    }


@pytest.mark.asyncio
async def test_duplicate_url_creates_single_row(migrated_db, db_session: AsyncSession):
    worker = NewsFetchWorker(
        registry=_test_registry(),
        session_factory=async_session_factory,
    )
    stats = await worker.run_once(
        feed_bodies={"test": _read_fixture("duplicate_url.xml")},
    )

    assert stats.created == 1
    assert stats.skipped_url == 1

    count = await db_session.scalar(select(func.count()).select_from(NewsItem))
    assert count == 1


@pytest.mark.asyncio
async def test_utm_params_deduped_by_normalized_url(migrated_db, db_session: AsyncSession):
    worker = NewsFetchWorker(
        registry=_test_registry(),
        session_factory=async_session_factory,
    )
    stats = await worker.run_once(
        feed_bodies={"test": _read_fixture("utm_url.xml")},
    )

    assert stats.created == 1
    assert stats.skipped_url == 1

    item = await db_session.scalar(select(NewsItem))
    assert item is not None
    assert item.source_url == "https://example.com/news/tracked"


@pytest.mark.asyncio
async def test_short_snippet_fetches_article_body(migrated_db):
    article_text = "Full article body " * 40

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/news/short-article":
            return httpx.Response(
                200,
                text=f"<html><body><article><p>{article_text}</p></article></body></html>",
            )
        raise AssertionError(f"unexpected request: {request.url}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        entries = await fetch_feed(
            "https://example.com/feed.xml",
            client=client,
            feed_body=_read_fixture("short_snippet.xml"),
        )
        body = await resolve_entry_body(entries[0], client=client)

    assert body == article_text.strip()
    assert content_hash(body) is not None


@pytest.mark.asyncio
async def test_content_hash_dedup_skips_syndicated_body(db_session: AsyncSession):
    from services.news.db.repository import NewsItemRepository

    repo = NewsItemRepository(db_session)
    body = "Shared syndicated article body for dedup testing."

    first = await ingest_article(
        repo,
        db_session,
        source_url="https://example.com/syndicated-a",
        body_text=body,
    )
    second = await ingest_article(
        repo,
        db_session,
        source_url="https://example.com/syndicated-b",
        body_text=body,
    )

    assert first is IngestResult.CREATED
    assert second is IngestResult.SKIPPED_HASH

    count = await db_session.scalar(select(func.count()).select_from(NewsItem))
    assert count == 1
