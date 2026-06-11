"""News metadata and /status countdown tests (U23)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from telegram import Message, Update

from services.bot.handlers.status import format_countdown, format_status_message, status_command
from services.metadata.main import app
from services.news.slot_clock import next_news_at, seconds_until_next_news

CITIES_YAML = Path(__file__).resolve().parents[1] / "broadcast" / "liquidsoap" / "cities.yaml"


@pytest.fixture
def metadata_client(monkeypatch):
    monkeypatch.setenv("CITIES_YAML_PATH", str(CITIES_YAML))
    monkeypatch.setenv("DEFAULT_CITY_TAG", "moscow")
    with TestClient(app) as test_client:
        yield test_client


def test_now_playing_news_pair_maps_to_content_type_news(metadata_client):
    mock_redis = MagicMock()
    mock_redis.hgetall.return_value = {
        "type": "NEWS_PAIR",
        "title": "Сейчас новости",
        "artist": "",
        "started_at": "1717867800",
        "duration_sec": "90",
    }
    app.state.redis = mock_redis

    response = metadata_client.get("/api/now-playing/moscow")
    assert response.status_code == 200
    payload = response.json()
    assert payload["content_type"] == "news"
    assert payload["title"] == "Сейчас новости"
    assert payload["artist"] is None


def test_next_news_at_enqueue_boundaries():
    assert next_news_at(datetime(2026, 6, 11, 10, 14, 30, tzinfo=UTC)) == datetime(
        2026, 6, 11, 10, 15, tzinfo=UTC
    )
    assert next_news_at(datetime(2026, 6, 11, 10, 15, 0, tzinfo=UTC)) == datetime(
        2026, 6, 11, 10, 15, tzinfo=UTC
    )
    assert next_news_at(datetime(2026, 6, 11, 10, 16, 0, tzinfo=UTC)) == datetime(
        2026, 6, 11, 10, 30, tzinfo=UTC
    )
    assert next_news_at(datetime(2026, 6, 11, 10, 45, 30, tzinfo=UTC)) == datetime(
        2026, 6, 11, 10, 45, tzinfo=UTC
    )
    assert next_news_at(datetime(2026, 6, 11, 10, 46, 0, tzinfo=UTC)) == datetime(
        2026, 6, 11, 11, 0, tzinfo=UTC
    )


def test_seconds_until_next_news():
    now = datetime(2026, 6, 11, 10, 14, 0, tzinfo=UTC)
    assert seconds_until_next_news(now) == pytest.approx(60.0, rel=0.01)


def test_format_countdown():
    assert format_countdown(0) == "сейчас"
    assert format_countdown(45) == "45 сек"
    assert format_countdown(125) == "2 мин 5 сек"
    assert format_countdown(3665) == "1 ч 1 мин"


def test_format_status_message():
    now = datetime(2026, 6, 11, 10, 14, 0, tzinfo=UTC)
    text = format_status_message(city_tag="moscow", now=now)
    assert "Москва" in text
    assert "10:15 UTC" in text
    assert "1 мин" in text


@pytest.mark.asyncio
async def test_status_command_replies_with_next_news_at(monkeypatch):
    fixed_now = datetime(2026, 6, 11, 10, 29, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "services.bot.handlers.status.format_status_message",
        lambda *, city_tag, now=None: format_status_message(city_tag=city_tag, now=fixed_now),
    )

    message = MagicMock(spec=Message)
    message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {"default_city": "spb"}
    update = Update(update_id=1, message=message)

    await status_command(update, context)

    message.reply_text.assert_awaited_once()
    reply = message.reply_text.await_args.args[0]
    assert "Санкт-Петербург" in reply
    assert "10:30 UTC" in reply
