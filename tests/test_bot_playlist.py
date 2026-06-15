"""Bot /playlist admin handler tests — U27."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from telegram import Message, Update

from services.bot.handlers.playlist import playlist_command
from services.bot.middleware.auth import is_admin
from services.db.migrate import run_migrations
from services.db.models import PlaylistConfig
from services.db.session import async_session_factory, reset_engine
from services.music.config_service import PlaylistConfigService

SAMPLE_RULES = """\
version: 1
default:
  yandex_playlist_ids:
    - "100:1"
  max_track_duration_sec: 300
  blocklisted_artists: []
cities:
  moscow:
    yandex_playlist_ids:
      - "200:3"
"""


@pytest.fixture(autouse=True)
def _reset_db_engine():
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
async def migrated_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    rules_path = tmp_path / "playlist_rules.yaml"
    rules_path.write_text(SAMPLE_RULES, encoding="utf-8")
    monkeypatch.setenv(
        "DATABASE_URL",
        os.environ.get("DATABASE_URL", "postgresql://fm21:fm21dev@postgres:5432/fm21"),
    )
    monkeypatch.setenv("PLAYLIST_RULES_PATH", str(rules_path))
    await run_migrations()
    yield rules_path
    from services.db.session import get_engine
    from sqlalchemy import text

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE playlist_config RESTART IDENTITY CASCADE"))


def _make_update(
    *,
    args: list[str] | None = None,
    user_id: int = 7,
    user_data: dict | None = None,
) -> tuple[Update, MagicMock]:
    from telegram import Chat, User

    user = User(id=user_id, first_name="Admin", is_bot=False)
    chat = Chat(id=100, type="private")
    message = MagicMock(spec=Message)
    message.chat = chat
    message.reply_text = AsyncMock()
    message.from_user = user

    context = MagicMock()
    context.args = args or []
    context.user_data = user_data if user_data is not None else {"default_city": "moscow"}

    update = Update(update_id=1, message=message)
    return update, context


@pytest.mark.asyncio
async def test_playlist_usage_without_args() -> None:
    update, context = _make_update(args=[])
    with patch.dict(os.environ, {"TELEGRAM_ADMIN_IDS": "7"}):
        await playlist_command(update, context)
    update.message.reply_text.assert_awaited_once()
    assert "/playlist" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_playlist_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "99")
    update, context = _make_update(args=["999:9"], user_id=7)
    await playlist_command(update, context)
    update.message.reply_text.assert_awaited_once()
    assert "администратор" in update.message.reply_text.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_playlist_rejects_invalid_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "7")
    update, context = _make_update(args=["not-a-playlist"])
    await playlist_command(update, context)
    assert "формат" in update.message.reply_text.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_playlist_rejects_all_city(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "7")
    update, context = _make_update(args=["999:9"], user_data={"default_city": "all"})
    await playlist_command(update, context)
    assert "одного города" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_playlist_updates_db_for_operator_city(
    migrated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "7")
    assert is_admin(7)

    update, context = _make_update(args=["888:8"])
    await playlist_command(update, context)

    async with async_session_factory()() as session:
        row = (
            await session.execute(
                select(PlaylistConfig).where(PlaylistConfig.city_tag == "moscow")
            )
        ).scalar_one()
        assert row.rules_json["yandex_playlist_ids"] == ["888:8"]

        service = PlaylistConfigService(session, rules_path=migrated_db)
        rules = await service.get_city_rules("moscow")
        assert rules.yandex_playlist_ids == ("888:8",)

    update.message.reply_text.assert_awaited_once()
    assert "888:8" in update.message.reply_text.await_args.args[0]
    assert "Москва" in update.message.reply_text.await_args.args[0]
