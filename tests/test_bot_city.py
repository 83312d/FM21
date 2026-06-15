"""Bot /city handler, auth allowlists, and operator prefs persistence — U25."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import CallbackQuery, Chat, Message, Update, User
from telegram.ext import ApplicationHandlerStop

from services.bot.handlers.city import city_command, get_operator_city
from services.bot.keyboards import build_city_keyboard
from services.bot.middleware.auth import auth_middleware, is_admin, is_operator
from services.bot.storage.operator_prefs import (
    get_stored_default_city,
    set_default_city,
)
from services.db.migrate import run_migrations
from services.db.session import async_session_factory, reset_engine
from services.injector.fanout import load_active_cities

@pytest.fixture(autouse=True)
def _reset_db_engine():
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
async def migrated_db(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        os.environ.get("DATABASE_URL", "postgresql://fm21:fm21dev@postgres:5432/fm21"),
    )
    await run_migrations()
    yield
    engine = None
    from services.db.session import get_engine

    engine = get_engine()
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE operator_prefs RESTART IDENTITY CASCADE"))


def _make_update(
    *,
    args: list[str] | None = None,
    user_id: int = 42,
    user_data: dict | None = None,
) -> tuple[Update, MagicMock]:
    user = User(id=user_id, first_name="Op", is_bot=False)
    chat = Chat(id=100, type="private")
    message = MagicMock(spec=Message)
    message.chat = chat
    message.chat_id = chat.id
    message.reply_text = AsyncMock()
    message.from_user = user

    context = MagicMock()
    context.args = args or []
    context.user_data = user_data if user_data is not None else {}

    update = Update(update_id=1, message=message)
    return update, context


class TestBuildCityKeyboard:
    def test_keyboard_matches_active_cities(self) -> None:
        path = os.environ.get("CITIES_YAML_PATH", "broadcast/liquidsoap/cities.yaml")
        active = load_active_cities(path)
        markup = build_city_keyboard(cities_yaml_path=path)
        callback_tags = [
            button.callback_data.split(":", 1)[1]
            for row in markup.inline_keyboard
            for button in row
        ]
        assert callback_tags == [*active, "all"]


class TestAuthAllowlists:
    def test_denied_when_allowlists_empty_without_open_access(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TELEGRAM_OPERATOR_IDS", raising=False)
        monkeypatch.delenv("TELEGRAM_ADMIN_IDS", raising=False)
        monkeypatch.delenv("BOT_OPEN_ACCESS", raising=False)
        assert is_operator(999) is False

    def test_open_access_when_flag_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_OPERATOR_IDS", raising=False)
        monkeypatch.delenv("TELEGRAM_ADMIN_IDS", raising=False)
        monkeypatch.setenv("BOT_OPEN_ACCESS", "1")
        assert is_operator(999) is True

    def test_operator_list_restricts_access(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "42,100")
        monkeypatch.delenv("TELEGRAM_ADMIN_IDS", raising=False)
        assert is_operator(42) is True
        assert is_operator(7) is False

    def test_admin_counts_as_operator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "42")
        monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "7")
        assert is_operator(7) is True
        assert is_admin(7) is True
        assert is_admin(42) is False

    @pytest.mark.asyncio
    async def test_auth_middleware_blocks_denied_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TELEGRAM_OPERATOR_IDS", "42")
        update, context = _make_update(user_id=99)
        with pytest.raises(ApplicationHandlerStop):
            await auth_middleware(update, context)
        update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
class TestCityCommand:
    async def test_city_no_args_shows_current(self) -> None:
        update, context = _make_update(args=[])
        context.user_data["default_city"] = "spb"
        await city_command(update, context)
        update.message.reply_text.assert_awaited_once()
        assert "Санкт-Петербург" in update.message.reply_text.await_args.args[0]

    async def test_city_sets_moscow(self, migrated_db) -> None:
        update, context = _make_update(args=["moscow"], user_id=42)
        with patch(
            "services.bot.handlers.city.set_default_city", new_callable=AsyncMock
        ) as mock_save:
            await city_command(update, context)
        mock_save.assert_awaited_once_with(42, "moscow")
        assert context.user_data["default_city"] == "moscow"
        update.message.reply_text.assert_awaited_once()
        assert "Москва" in update.message.reply_text.await_args.args[0]

    async def test_city_sets_all(self, migrated_db) -> None:
        update, context = _make_update(args=["all"], user_id=42)
        with patch(
            "services.bot.handlers.city.set_default_city", new_callable=AsyncMock
        ) as mock_save:
            await city_command(update, context)
        mock_save.assert_awaited_once_with(42, "all")
        assert context.user_data["default_city"] == "all"

    async def test_city_rejects_unknown_tag(self) -> None:
        update, context = _make_update(args=["berlin"])
        await city_command(update, context)
        assert "default_city" not in context.user_data
        update.message.reply_text.assert_awaited_once()
        assert "Неизвестный город" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
class TestOperatorPrefsPersistence:
    async def test_set_and_get_default_city(self, migrated_db) -> None:
        await set_default_city(42, "spb")
        assert await get_stored_default_city(42) == "spb"

    async def test_upsert_updates_city(self, migrated_db) -> None:
        await set_default_city(42, "moscow")
        await set_default_city(42, "all")
        assert await get_stored_default_city(42) == "all"

    async def test_persistence_survives_restart(self, migrated_db) -> None:
        await set_default_city(42, "spb")
        reset_engine()

        assert await get_stored_default_city(42) == "spb"

        context = MagicMock()
        context.user_data = {}
        from services.bot.middleware.auth import ensure_operator_city_loaded

        await ensure_operator_city_loaded(context, 42)
        assert context.user_data["default_city"] == "spb"
        assert get_operator_city(context) == "spb"


class TestGetOperatorCity:
    def test_falls_back_to_env_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEFAULT_OPERATOR_CITY", "moscow")
        context = MagicMock()
        context.user_data = {}
        assert get_operator_city(context) == "moscow"
