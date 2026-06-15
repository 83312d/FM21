"""PostgreSQL repository for ads lifecycle (U24)."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.models import Ad, AdStatus


class AdRepository:
    """Async repository for ads table workflow."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_pending(
        self,
        *,
        telegram_user_id: int,
        city_tag: str,
        audio_url: str,
    ) -> Ad:
        ad = Ad(
            telegram_user_id=telegram_user_id,
            city_tag=city_tag,
            audio_url=audio_url,
            status=AdStatus.PENDING,
        )
        self._session.add(ad)
        await self._session.flush()
        await self._session.refresh(ad)
        return ad

    async def mark_queued(self, ad_id: int) -> Ad:
        await self._session.execute(
            update(Ad).where(Ad.id == ad_id).values(status=AdStatus.QUEUED)
        )
        await self._session.flush()
        ad = await self._session.get(Ad, ad_id)
        if ad is None:
            raise ValueError(f"Ad {ad_id} not found")
        return ad

    async def mark_rejected(self, ad_id: int) -> Ad:
        await self._session.execute(
            update(Ad).where(Ad.id == ad_id).values(status=AdStatus.REJECTED)
        )
        await self._session.flush()
        ad = await self._session.get(Ad, ad_id)
        if ad is None:
            raise ValueError(f"Ad {ad_id} not found")
        return ad

    async def get_by_id(self, ad_id: int) -> Ad | None:
        return await self._session.get(Ad, ad_id)

    async def count_by_status(self, status: AdStatus) -> int:
        result = await self._session.execute(select(Ad).where(Ad.status == status))
        return len(result.scalars().all())
