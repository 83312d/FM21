"""Playlist rules loader tests (U11)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services.db.migrate import run_migrations
from services.db.models import PlaylistConfig
from services.db.session import async_session_factory, get_engine, reset_engine
from services.music.config_service import PlaylistConfigService
from services.music.provider import TrackInfo
from services.music.rules_loader import (
    filter_tracks,
    load_playlist_rules,
    resolve_city_rules,
    validate_playlist_rules_at_boot,
)
from services.music.rules_schema import PlaylistRulesError

SAMPLE_RULES = """\
version: 1
default:
  yandex_playlist_ids:
    - "100:1"
    - "100:2"
  max_track_duration_sec: 300
  blocklisted_artists:
    - "Blocked Artist"
cities:
  moscow:
    yandex_playlist_ids:
      - "200:3"
  spb:
    yandex_playlist_ids:
      - "300:4"
"""


@pytest.fixture
def rules_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "playlist_rules.yaml"
    path.write_text(SAMPLE_RULES, encoding="utf-8")
    return path


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
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE playlist_config RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db_session(migrated_db) -> AsyncSession:
    async with async_session_factory()() as session:
        yield session


def test_city_override_selects_different_playlist(rules_yaml: Path):
    document = load_playlist_rules(rules_yaml)

    default_rules = resolve_city_rules(document, "unknown-city")
    moscow_rules = resolve_city_rules(document, "moscow")
    spb_rules = resolve_city_rules(document, "spb")

    assert default_rules.yandex_playlist_ids == ("100:1", "100:2")
    assert moscow_rules.yandex_playlist_ids == ("200:3",)
    assert spb_rules.yandex_playlist_ids == ("300:4",)


def test_blocklisted_artist_filtered(rules_yaml: Path):
    document = load_playlist_rules(rules_yaml)
    rules = resolve_city_rules(document, "moscow")

    tracks = [
        TrackInfo(track_id="1", title="Allowed", artist="Safe Artist", duration_sec=120),
        TrackInfo(track_id="2", title="Blocked", artist="Blocked Artist", duration_sec=120),
        TrackInfo(
            track_id="3",
            title="Combo",
            artist="Safe Artist, Blocked Artist",
            duration_sec=120,
        ),
        TrackInfo(track_id="4", title="Too Long", artist="Safe Artist", duration_sec=400),
    ]

    filtered = filter_tracks(tracks, rules)

    assert [track.track_id for track in filtered] == ["1"]


def test_malformed_yaml_raises_startup_error(tmp_path: Path):
    bad_path = tmp_path / "playlist_rules.yaml"
    bad_path.write_text("default:\n  yandex_playlist_ids: [", encoding="utf-8")

    with pytest.raises(PlaylistRulesError, match="malformed"):
        load_playlist_rules(bad_path)

    with pytest.raises(PlaylistRulesError, match="malformed"):
        validate_playlist_rules_at_boot(bad_path)


def test_invalid_schema_raises_startup_error(tmp_path: Path):
    bad_path = tmp_path / "playlist_rules.yaml"
    bad_path.write_text(
        "default:\n  yandex_playlist_ids: []\n  max_track_duration_sec: 300\n",
        encoding="utf-8",
    )

    with pytest.raises(PlaylistRulesError, match="non-empty list"):
        load_playlist_rules(bad_path)


@pytest.mark.asyncio
async def test_db_override_wins_when_newer_than_yaml(
    rules_yaml: Path,
    db_session: AsyncSession,
):
    yaml_mtime = (datetime.now(UTC) - timedelta(hours=1)).timestamp()
    os.utime(rules_yaml, (yaml_mtime, yaml_mtime))

    db_session.add(
        PlaylistConfig(
            city_tag="moscow",
            rules_json={"yandex_playlist_ids": ["999:9"]},
            updated_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    service = PlaylistConfigService(db_session, rules_path=rules_yaml)
    rules = await service.get_city_rules("moscow")

    assert rules.yandex_playlist_ids == ("999:9",)


@pytest.mark.asyncio
async def test_yaml_wins_when_newer_than_db(
    rules_yaml: Path,
    db_session: AsyncSession,
):
    yaml_mtime = datetime.now(UTC).timestamp()
    os.utime(rules_yaml, (yaml_mtime, yaml_mtime))

    db_session.add(
        PlaylistConfig(
            city_tag="moscow",
            rules_json={"yandex_playlist_ids": ["999:9"]},
            updated_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    await db_session.commit()

    service = PlaylistConfigService(db_session, rules_path=rules_yaml)
    rules = await service.get_city_rules("moscow")

    assert rules.yandex_playlist_ids == ("200:3",)
