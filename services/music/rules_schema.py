"""Typed playlist policy schema and validation (U11)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_PLAYLIST_ID_RE = re.compile(r"^\d+:\d+$")


class PlaylistRulesError(ValueError):
    """Invalid playlist_rules.yaml or merged config."""


@dataclass(frozen=True, slots=True)
class DefaultPlaylistRules:
    yandex_playlist_ids: tuple[str, ...]
    max_track_duration_sec: int
    blocklisted_artists: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CityRulesOverride:
    yandex_playlist_ids: tuple[str, ...] | None = None
    max_track_duration_sec: int | None = None
    blocklisted_artists: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class PlaylistRulesDocument:
    default: DefaultPlaylistRules
    cities: dict[str, CityRulesOverride]
    source_path: Path
    loaded_at: datetime
    mtime: float


@dataclass(frozen=True, slots=True)
class ResolvedCityRules:
    city_tag: str
    yandex_playlist_ids: tuple[str, ...]
    max_track_duration_sec: int
    blocklisted_artists: frozenset[str]


def normalize_artist(value: str) -> str:
    return value.strip().casefold()


def _validate_playlist_ids(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise PlaylistRulesError(f"{field} must be a non-empty list of playlist ids")
    ids: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _PLAYLIST_ID_RE.match(item.strip()):
            raise PlaylistRulesError(
                f"{field} contains invalid playlist id {item!r}; expected '<uid>:<kind>'"
            )
        ids.append(item.strip())
    return tuple(ids)


def _validate_blocklist(value: Any, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise PlaylistRulesError(f"{field} must be a list of artist names")
    artists: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PlaylistRulesError(f"{field} entries must be non-empty strings")
        artists.append(normalize_artist(item))
    return tuple(artists)


def _validate_max_duration(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PlaylistRulesError(f"{field} must be a positive integer")
    return value


def parse_default_rules(data: dict[str, Any]) -> DefaultPlaylistRules:
    return DefaultPlaylistRules(
        yandex_playlist_ids=_validate_playlist_ids(
            data.get("yandex_playlist_ids"), field="default.yandex_playlist_ids"
        ),
        max_track_duration_sec=_validate_max_duration(
            data.get("max_track_duration_sec"), field="default.max_track_duration_sec"
        ),
        blocklisted_artists=_validate_blocklist(
            data.get("blocklisted_artists", []), field="default.blocklisted_artists"
        ),
    )


def parse_city_override(data: dict[str, Any], *, city_tag: str) -> CityRulesOverride:
    playlist_ids = data.get("yandex_playlist_ids")
    max_duration = data.get("max_track_duration_sec")
    blocklist = data.get("blocklisted_artists")

    return CityRulesOverride(
        yandex_playlist_ids=(
            _validate_playlist_ids(playlist_ids, field=f"cities.{city_tag}.yandex_playlist_ids")
            if playlist_ids is not None
            else None
        ),
        max_track_duration_sec=(
            _validate_max_duration(
                max_duration, field=f"cities.{city_tag}.max_track_duration_sec"
            )
            if max_duration is not None
            else None
        ),
        blocklisted_artists=(
            _validate_blocklist(blocklist, field=f"cities.{city_tag}.blocklisted_artists")
            if blocklist is not None
            else None
        ),
    )


def parse_rules_document(
    raw: Any,
    *,
    source_path: Path,
    loaded_at: datetime,
    mtime: float,
) -> PlaylistRulesDocument:
    if not isinstance(raw, dict):
        raise PlaylistRulesError("playlist_rules.yaml root must be a mapping")

    default_raw = raw.get("default")
    if not isinstance(default_raw, dict):
        raise PlaylistRulesError("playlist_rules.yaml must contain a 'default' mapping")

    cities_raw = raw.get("cities", {})
    if cities_raw is None:
        cities_raw = {}
    if not isinstance(cities_raw, dict):
        raise PlaylistRulesError("playlist_rules.yaml 'cities' must be a mapping")

    cities: dict[str, CityRulesOverride] = {}
    for city_tag, override_raw in cities_raw.items():
        if not isinstance(city_tag, str) or not city_tag.strip():
            raise PlaylistRulesError("city tags must be non-empty strings")
        if not isinstance(override_raw, dict):
            raise PlaylistRulesError(f"cities.{city_tag} must be a mapping")
        cities[city_tag.strip()] = parse_city_override(override_raw, city_tag=city_tag.strip())

    return PlaylistRulesDocument(
        default=parse_default_rules(default_raw),
        cities=cities,
        source_path=source_path,
        loaded_at=loaded_at,
        mtime=mtime,
    )


def merge_rules_dict(base: ResolvedCityRules, override: dict[str, Any]) -> ResolvedCityRules:
    playlist_ids = base.yandex_playlist_ids
    if "yandex_playlist_ids" in override:
        playlist_ids = _validate_playlist_ids(
            override["yandex_playlist_ids"], field="rules_json.yandex_playlist_ids"
        )

    max_duration = base.max_track_duration_sec
    if "max_track_duration_sec" in override:
        max_duration = _validate_max_duration(
            override["max_track_duration_sec"], field="rules_json.max_track_duration_sec"
        )

    blocklist = base.blocklisted_artists
    if "blocklisted_artists" in override:
        blocklist = frozenset(
            _validate_blocklist(override["blocklisted_artists"], field="rules_json.blocklisted_artists")
        )

    return ResolvedCityRules(
        city_tag=base.city_tag,
        yandex_playlist_ids=playlist_ids,
        max_track_duration_sec=max_duration,
        blocklisted_artists=blocklist,
    )


def yaml_mtime_as_utc(mtime: float) -> datetime:
    return datetime.fromtimestamp(mtime, tz=UTC)
