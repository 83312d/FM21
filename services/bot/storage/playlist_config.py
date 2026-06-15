"""Admin playlist overrides in PostgreSQL (U27)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert

from services.db.models import PlaylistConfig
from services.db.session import async_session_factory


async def upsert_city_playlist(city_tag: str, playlist_id: str) -> None:
    async with async_session_factory()() as session:
        stmt = (
            insert(PlaylistConfig)
            .values(
                city_tag=city_tag,
                rules_json={"yandex_playlist_ids": [playlist_id]},
                updated_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                index_elements=[PlaylistConfig.city_tag],
                set_={
                    "rules_json": {"yandex_playlist_ids": [playlist_id]},
                    "updated_at": datetime.now(UTC),
                },
            )
        )
        await session.execute(stmt)
        await session.commit()
