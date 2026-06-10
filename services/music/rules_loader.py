"""Load and resolve playlist_rules.yaml (U11, R24, R31)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import yaml

from services.music.provider import TrackInfo
from services.music.rules_schema import (
    CityRulesOverride,
    DefaultPlaylistRules,
    PlaylistRulesDocument,
    PlaylistRulesError,
    ResolvedCityRules,
    merge_rules_dict,
    normalize_artist,
    parse_rules_document,
    yaml_mtime_as_utc,
)

DEFAULT_RULES_PATH = Path(__file__).with_name("playlist_rules.yaml")


def rules_path_from_env() -> Path:
    env_path = os.environ.get("PLAYLIST_RULES_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_RULES_PATH


def load_playlist_rules(path: Path | str | None = None) -> PlaylistRulesDocument:
    """Parse and validate playlist_rules.yaml. Raises PlaylistRulesError on invalid input."""
    rules_path = Path(path) if path is not None else rules_path_from_env()
    if not rules_path.is_file():
        raise PlaylistRulesError(f"playlist rules file not found: {rules_path}")

    loaded_at = datetime.now(UTC)
    mtime = rules_path.stat().st_mtime

    try:
        with rules_path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise PlaylistRulesError(f"malformed playlist_rules.yaml: {exc}") from exc

    return parse_rules_document(
        raw,
        source_path=rules_path,
        loaded_at=loaded_at,
        mtime=mtime,
    )


def validate_playlist_rules_at_boot(path: Path | str | None = None) -> PlaylistRulesDocument:
    """Fail fast during service startup when YAML is invalid."""
    return load_playlist_rules(path)


def _apply_city_override(
    base: DefaultPlaylistRules,
    override: CityRulesOverride | None,
) -> ResolvedCityRules:
    playlist_ids = override.yandex_playlist_ids if override and override.yandex_playlist_ids else base.yandex_playlist_ids
    max_duration = (
        override.max_track_duration_sec
        if override and override.max_track_duration_sec is not None
        else base.max_track_duration_sec
    )
    blocklist = (
        override.blocklisted_artists
        if override and override.blocklisted_artists is not None
        else base.blocklisted_artists
    )
    return ResolvedCityRules(
        city_tag="",
        yandex_playlist_ids=playlist_ids,
        max_track_duration_sec=max_duration,
        blocklisted_artists=frozenset(blocklist),
    )


def resolve_city_rules(
    document: PlaylistRulesDocument,
    city_tag: str,
    *,
    db_rules: dict | None = None,
    db_updated_at: datetime | None = None,
) -> ResolvedCityRules:
    """Merge default YAML, per-city YAML override, and optional DB row."""
    city_override = document.cities.get(city_tag)
    resolved = _apply_city_override(document.default, city_override)
    resolved = ResolvedCityRules(
        city_tag=city_tag,
        yandex_playlist_ids=resolved.yandex_playlist_ids,
        max_track_duration_sec=resolved.max_track_duration_sec,
        blocklisted_artists=resolved.blocklisted_artists,
    )

    if not db_rules or db_updated_at is None:
        return resolved

    if db_updated_at <= yaml_mtime_as_utc(document.mtime):
        return resolved

    return merge_rules_dict(resolved, db_rules)


def _artist_tokens(artist: str) -> set[str]:
    return {normalize_artist(part) for part in artist.split(",") if part.strip()}


def is_track_allowed(track: TrackInfo, rules: ResolvedCityRules) -> bool:
    if rules.blocklisted_artists:
        tokens = _artist_tokens(track.artist)
        if tokens & rules.blocklisted_artists:
            return False

    if track.duration_sec is not None and track.duration_sec > rules.max_track_duration_sec:
        return False

    return True


def filter_tracks(tracks: list[TrackInfo], rules: ResolvedCityRules) -> list[TrackInfo]:
    return [track for track in tracks if is_track_allowed(track, rules)]
