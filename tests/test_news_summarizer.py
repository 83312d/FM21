"""News summarizer tests (U17) — mocked GigaChat, no live API."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.migrate import run_migrations
from services.db.models import NewsItemStatus
from services.db.session import async_session_factory, get_engine, reset_engine
from services.news.db.models import NewsFetchInput
from services.news.db.repository import NewsItemRepository
from services.news.summarizer.validate import (
    MAX_WORDS,
    MIN_WORDS,
    count_words,
    is_valid_word_count,
)
from services.news.workers.summarize import (
    SummarizeResult,
    generate_summary,
    summarize_news_item,
)


def _ru_words(count: int, word: str = "слово") -> str:
    return " ".join([word] * count)


@dataclass
class MockSummarizerClient:
    responses: list[str] = field(default_factory=list)
    calls: list[bool] = field(default_factory=list)

    async def summarize(self, source_text: str, *, tightened: bool = False) -> str:
        self.calls.append(tightened)
        if not self.responses:
            raise AssertionError("MockSummarizerClient has no more responses")
        return self.responses.pop(0)


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
        from sqlalchemy import text

        await conn.execute(text("TRUNCATE TABLE news_items RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db_session(migrated_db) -> AsyncSession:
    async with async_session_factory()() as session:
        yield session


@pytest.fixture
def repo(db_session: AsyncSession) -> NewsItemRepository:
    return NewsItemRepository(db_session)


def test_count_words_accepts_150_to_250_range():
    assert count_words(_ru_words(149)) == 149
    assert count_words(_ru_words(150)) == 150
    assert count_words(_ru_words(180)) == 180
    assert count_words(_ru_words(250)) == 250
    assert count_words(_ru_words(251)) == 251

    assert not is_valid_word_count(_ru_words(MIN_WORDS - 1))
    assert is_valid_word_count(_ru_words(180))
    assert is_valid_word_count(_ru_words(MIN_WORDS))
    assert is_valid_word_count(_ru_words(MAX_WORDS))
    assert not is_valid_word_count(_ru_words(MAX_WORDS + 1))


@pytest.mark.asyncio
async def test_mock_180_words_accepted(repo: NewsItemRepository, db_session: AsyncSession):
    item = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/article-1", content_hash="hash-1")
    )
    await db_session.commit()

    client = MockSummarizerClient(responses=[_ru_words(180)])
    result = await summarize_news_item(
        repo,
        item.id,
        "Source article about a new database release.",
        client,
    )
    await db_session.commit()

    assert result is SummarizeResult.SUMMARIZED
    assert client.calls == [False]

    updated = await repo.get_by_id(item.id)
    assert updated is not None
    assert updated.status == NewsItemStatus.SUMMARIZED
    assert count_words(updated.summary_ru or "") == 180


@pytest.mark.asyncio
async def test_out_of_range_retries_once(repo: NewsItemRepository, db_session: AsyncSession):
    item = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/article-2", content_hash="hash-2")
    )
    await db_session.commit()

    client = MockSummarizerClient(responses=[_ru_words(100), _ru_words(180)])
    result = await summarize_news_item(
        repo,
        item.id,
        "Source article about cloud infrastructure.",
        client,
    )
    await db_session.commit()

    assert result is SummarizeResult.SUMMARIZED
    assert client.calls == [False, True]

    updated = await repo.get_by_id(item.id)
    assert updated is not None
    assert updated.status == NewsItemStatus.SUMMARIZED
    assert count_words(updated.summary_ru or "") == 180


@pytest.mark.asyncio
async def test_out_of_range_after_retry_marks_failed(
    repo: NewsItemRepository,
    db_session: AsyncSession,
):
    item = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/article-3", content_hash="hash-3")
    )
    await db_session.commit()

    client = MockSummarizerClient(responses=[_ru_words(100), _ru_words(120)])
    result = await summarize_news_item(
        repo,
        item.id,
        "Source article about security patches.",
        client,
    )
    await db_session.commit()

    assert result is SummarizeResult.FAILED
    assert client.calls == [False, True]

    updated = await repo.get_by_id(item.id)
    assert updated is not None
    assert updated.status == NewsItemStatus.FAILED
    assert updated.summary_ru is None


@pytest.mark.asyncio
async def test_already_summarized_is_idempotent(
    repo: NewsItemRepository,
    db_session: AsyncSession,
):
    item = await repo.create_from_fetch(
        NewsFetchInput(source_url="https://example.com/article-4", content_hash="hash-4")
    )
    await db_session.commit()
    await repo.update_summary(item.id, _ru_words(180))
    await db_session.commit()

    client = MockSummarizerClient(responses=[_ru_words(200)])
    result = await summarize_news_item(
        repo,
        item.id,
        "Source article that should not be re-summarized.",
        client,
    )

    assert result is SummarizeResult.SKIPPED
    assert client.calls == []

    updated = await repo.get_by_id(item.id)
    assert updated is not None
    assert updated.status == NewsItemStatus.SUMMARIZED
    assert count_words(updated.summary_ru or "") == 180


@pytest.mark.asyncio
async def test_generate_summary_returns_none_without_third_attempt():
    client = MockSummarizerClient(responses=[_ru_words(90), _ru_words(300)])

    summary = await generate_summary("source", client)

    assert summary is None
    assert client.calls == [False, True]
