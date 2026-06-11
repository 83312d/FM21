"""Dedup and persist fetched articles (U16)."""

from __future__ import annotations

import enum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.news.db.models import NewsFetchInput
from services.news.db.repository import NewsItemRepository
from services.news.fetcher.normalize import content_hash, normalize_content, normalize_url

MIN_BODY_LEN = 30


class IngestResult(str, enum.Enum):
    CREATED = "created"
    SKIPPED_URL = "skipped_url"
    SKIPPED_HASH = "skipped_hash"
    SKIPPED_CONFLICT = "skipped_conflict"
    SKIPPED_EMPTY_BODY = "skipped_empty_body"


async def ingest_article(
    repo: NewsItemRepository,
    session: AsyncSession,
    *,
    source_url: str,
    body_text: str,
) -> IngestResult:
    """Insert a fetched article when URL and content_hash are new."""
    normalized_url = normalize_url(source_url)
    if not normalized_url:
        return IngestResult.SKIPPED_URL

    if len(normalize_content(body_text)) < MIN_BODY_LEN:
        return IngestResult.SKIPPED_EMPTY_BODY

    existing_url = await repo.get_by_source_url(normalized_url)
    if existing_url is not None:
        return IngestResult.SKIPPED_URL

    hash_value = content_hash(body_text)
    if hash_value is not None:
        existing_hash = await repo.get_by_content_hash(hash_value)
        if existing_hash is not None:
            return IngestResult.SKIPPED_HASH

    try:
        await repo.create_from_fetch(
            NewsFetchInput(
                source_url=normalized_url,
                content_hash=hash_value,
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return IngestResult.SKIPPED_CONFLICT

    return IngestResult.CREATED
