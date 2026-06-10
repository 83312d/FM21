"""Resolve per-city playlist policy from YAML + playlist_config DB (U11)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.models import PlaylistConfig
from services.music.rules_loader import (
    load_playlist_rules,
    resolve_city_rules,
    rules_path_from_env,
    validate_playlist_rules_at_boot,
)
from services.music.rules_schema import PlaylistRulesDocument, ResolvedCityRules


class PlaylistConfigService:
    """Loads playlist_rules.yaml and merges newer playlist_config rows per city."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        rules_path: Path | str | None = None,
    ) -> None:
        self._session = session
        self._rules_path = Path(rules_path) if rules_path is not None else rules_path_from_env()
        self._document: PlaylistRulesDocument | None = None

    @property
    def document(self) -> PlaylistRulesDocument:
        if self._document is None:
            self._document = load_playlist_rules(self._rules_path)
        return self._document

    def load_and_validate(self) -> PlaylistRulesDocument:
        self._document = validate_playlist_rules_at_boot(self._rules_path)
        return self._document

    def reload_yaml(self) -> PlaylistRulesDocument:
        self._document = load_playlist_rules(self._rules_path)
        return self._document

    async def get_city_rules(self, city_tag: str) -> ResolvedCityRules:
        row = (
            await self._session.execute(
                select(PlaylistConfig).where(PlaylistConfig.city_tag == city_tag)
            )
        ).scalar_one_or_none()

        return resolve_city_rules(
            self.document,
            city_tag,
            db_rules=row.rules_json if row else None,
            db_updated_at=row.updated_at if row else None,
        )
