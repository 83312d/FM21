"""Persist operator default city in PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from services.db.models import OperatorPrefs
from services.db.session import async_session_factory


async def get_stored_default_city(telegram_user_id: int) -> str | None:
    async with async_session_factory()() as session:
        row = (
            await session.execute(
                select(OperatorPrefs.default_city_tag).where(
                    OperatorPrefs.telegram_user_id == telegram_user_id
                )
            )
        ).scalar_one_or_none()
        return row


async def set_default_city(telegram_user_id: int, city_tag: str) -> None:
    now = datetime.now(UTC)
    async with async_session_factory()() as session:
        stmt = (
            insert(OperatorPrefs)
            .values(
                telegram_user_id=telegram_user_id,
                default_city_tag=city_tag,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[OperatorPrefs.telegram_user_id],
                set_={
                    "default_city_tag": city_tag,
                    "updated_at": now,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()
