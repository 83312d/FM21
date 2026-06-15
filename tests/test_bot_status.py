"""Bot /status handler tests — U27."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from telegram import Message, Update

from services.bot.clients.metadata_client import NowPlaying, QueueItemPreview, QueuePreview
from services.bot.handlers.status import format_status_message, status_command
from services.injector.fanout import build_queue_item
from services.metadata.main import app as metadata_app

CITY = "moscow"


def _make_update(*, user_data: dict | None = None) -> tuple[Update, MagicMock]:
    message = MagicMock(spec=Message)
    message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = user_data if user_data is not None else {"default_city": CITY}
    update = Update(update_id=1, message=message)
    return update, context


def test_format_status_includes_now_playing_and_queue() -> None:
    now = datetime(2026, 6, 11, 10, 14, 0, tzinfo=UTC)
    text = format_status_message(
        city_tag=CITY,
        now_playing=NowPlaying(
            title="Evening Drive",
            artist="FM21 Static",
            content_type="music",
            remaining_sec=120,
        ),
        queue=QueuePreview(
            city_tag=CITY,
            items=[
                QueueItemPreview(title="Voice ad", artist=None, content_type="ad", duration_sec=42),
                QueueItemPreview(
                    title="Ordered track",
                    artist="Band",
                    content_type="music",
                    duration_sec=180,
                ),
            ],
        ),
        now=now,
    )
    assert "Москва" in text
    assert "Evening Drive" in text
    assert "FM21 Static" in text
    assert "Voice ad" in text
    assert "Ordered track" in text
    assert "10:15 UTC" in text


def test_format_status_without_now_playing() -> None:
    text = format_status_message(
        city_tag=CITY,
        now_playing=None,
        queue=QueuePreview(city_tag=CITY, items=[]),
        now=datetime(2026, 6, 11, 10, 14, 0, tzinfo=UTC),
    )
    assert "нет данных" in text.lower() or "не играет" in text.lower()
    assert "Очередь пуста" in text


@pytest.mark.asyncio
async def test_status_command_rejects_all_city() -> None:
    update, context = _make_update(user_data={"default_city": "all"})
    await status_command(update, context)
    update.message.reply_text.assert_awaited_once()
    assert "одного города" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
@patch("services.bot.handlers.status.fetch_status", new_callable=AsyncMock)
async def test_status_command_fetches_metadata_for_operator_city(
    mock_fetch: AsyncMock,
) -> None:
    mock_fetch.return_value = format_status_message(
        city_tag=CITY,
        now_playing=NowPlaying(
            title="Live",
            artist=None,
            content_type="music",
            remaining_sec=60,
        ),
        queue=QueuePreview(city_tag=CITY, items=[]),
    )
    update, context = _make_update()
    await status_command(update, context)
    mock_fetch.assert_awaited_once_with(CITY)
    update.message.reply_text.assert_awaited_once_with(mock_fetch.return_value)


@pytest.mark.asyncio
@patch("services.bot.handlers.status.fetch_status", new_callable=AsyncMock)
async def test_status_command_surfaces_metadata_error(mock_fetch: AsyncMock) -> None:
    mock_fetch.return_value = "Не удалось получить статус эфира. Попробуйте позже."
    update, context = _make_update()
    await status_command(update, context)
    update.message.reply_text.assert_awaited_once()
    assert "Не удалось" in update.message.reply_text.await_args.args[0]


def test_status_preview_matches_redis_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """Queue lines in /status must match metadata GET /api/queue/{cityTag}."""
    from pathlib import Path
    from unittest.mock import MagicMock

    cities_yaml = Path(__file__).resolve().parents[1] / "broadcast" / "liquidsoap" / "cities.yaml"
    monkeypatch.setenv("CITIES_YAML_PATH", str(cities_yaml))

    mock_redis = MagicMock()
    ad_item = build_queue_item(
        item_type="AD",
        uri="file:///data/ads/test.mp3",
        city_tag=CITY,
        meta={"title": "Redis ad", "artist": "", "duration_sec": 40},
    )
    music_item = build_queue_item(
        item_type="MUSIC",
        uri="file:///data/music/bed.mp3",
        city_tag=CITY,
        meta={"title": "Redis bed", "artist": "FM21", "duration_sec": 200},
    )
    mock_redis.lrange.return_value = [
        json.dumps(music_item, separators=(",", ":")),
        json.dumps(ad_item, separators=(",", ":")),
    ]
    mock_redis.hgetall.return_value = {
        "type": "MUSIC",
        "title": "On air",
        "artist": "FM21",
        "started_at": "1717867800",
        "duration_sec": "240",
    }

    with TestClient(metadata_app) as client:
        metadata_app.state.redis = mock_redis
        queue_response = client.get(f"/api/queue/{CITY}")
        now_response = client.get(f"/api/now-playing/{CITY}")

    assert queue_response.status_code == 200
    assert now_response.status_code == 200
    queue_titles = [item["title"] for item in queue_response.json()["items"]]

    text = format_status_message(
        city_tag=CITY,
        now_playing=NowPlaying(
            title=now_response.json()["title"],
            artist=now_response.json()["artist"],
            content_type=now_response.json()["content_type"],
            remaining_sec=now_response.json()["remaining_sec"],
        ),
        queue=QueuePreview(
            city_tag=CITY,
            items=[
                QueueItemPreview(
                    title=item["title"],
                    artist=item["artist"],
                    content_type=item["content_type"],
                    duration_sec=item["duration_sec"],
                )
                for item in queue_response.json()["items"]
            ],
        ),
    )
    for title in queue_titles:
        assert title in text
