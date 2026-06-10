"""Bot /order handler tests — U14."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import CallbackQuery, Chat, Message, Update, User

from services.bot.handlers.order import order_callback, order_command
from services.bot.parsers.order import format_search_query, parse_order_args
from services.injector.fanout import build_queue_item
from services.music.provider import StreamUrl, TrackInfo

pytestmark = pytest.mark.usefixtures("queue_client")


def _make_update(
    *,
    text: str | None = None,
    args: list[str] | None = None,
    callback_data: str | None = None,
    user_data: dict | None = None,
) -> tuple[Update, MagicMock]:
    user = User(id=42, first_name="Op", is_bot=False)
    chat = Chat(id=100, type="private")
    message = MagicMock(spec=Message)
    message.chat = chat
    message.chat_id = chat.id
    message.reply_text = AsyncMock()
    message.edit_text = AsyncMock()
    message.edit_reply_markup = AsyncMock()

    context = MagicMock()
    context.args = args or []
    context.user_data = user_data if user_data is not None else {}

    if callback_data is not None:
        query = MagicMock(spec=CallbackQuery)
        query.data = callback_data
        query.message = message
        query.answer = AsyncMock()
        update = Update(update_id=1, callback_query=query)
        return update, context

    message.text = text
    update = Update(update_id=1, message=message)
    return update, context


class TestParseOrderArgs:
    def test_valid_em_dash(self) -> None:
        assert parse_order_args(["Bohemian", "Rhapsody", "—", "Queen"]) == (
            "Bohemian Rhapsody",
            "Queen",
        )

    def test_missing_separator(self) -> None:
        assert parse_order_args(["Title", "Artist"]) is None

    def test_empty_args(self) -> None:
        assert parse_order_args([]) is None

    def test_format_search_query(self) -> None:
        assert format_search_query("Title", "Artist") == "Title Artist"


@pytest.mark.asyncio
async def test_order_command_usage_when_no_args() -> None:
    update, context = _make_update(args=[])
    await order_command(update, context)
    update.message.reply_text.assert_awaited_once_with(
        "Используйте: /order Название — Исполнитель"
    )


@pytest.mark.asyncio
async def test_order_command_rejects_all_city() -> None:
    update, context = _make_update(args=["Song", "—", "Band"])
    context.user_data["default_city"] = "all"
    await order_command(update, context)
    update.message.reply_text.assert_awaited_once()
    assert "одного города" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
@patch("services.bot.handlers.order.search_tracks", new_callable=AsyncMock)
async def test_order_command_no_results(mock_search: AsyncMock) -> None:
    mock_search.return_value = []
    update, context = _make_update(args=["Unknown", "—", "Nobody"])
    await order_command(update, context)
    mock_search.assert_awaited_once_with("Unknown Nobody", limit=3)
    update.message.reply_text.assert_awaited_once()
    assert "Ничего не найдено" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
@patch("services.bot.handlers.order.search_tracks", new_callable=AsyncMock)
async def test_order_command_shows_top_matches(mock_search: AsyncMock) -> None:
    tracks = [
        TrackInfo(track_id="1", title="A", artist="X", duration_sec=200),
        TrackInfo(track_id="2", title="B", artist="Y", duration_sec=180),
    ]
    mock_search.return_value = tracks
    update, context = _make_update(args=["Query", "—", "Band"])
    await order_command(update, context)
    update.message.reply_text.assert_awaited_once()
    assert update.message.reply_text.await_args.kwargs["reply_markup"] is not None
    assert context.user_data["pending_order_tracks"]["1"]["title"] == "A"


@pytest.mark.asyncio
@patch("services.bot.handlers.order.enqueue_music_order", new_callable=AsyncMock)
@patch("services.bot.handlers.order.resolve_stream_url", new_callable=AsyncMock)
async def test_order_confirm_enqueues_music_order(
    mock_resolve: AsyncMock,
    mock_enqueue: AsyncMock,
    injector_client,
    auth_headers,
    queue_client,
) -> None:
    from services.bot.clients.injector_client import EnqueueResult

    track = TrackInfo(track_id="bed-01", title="Bed 01", artist="FM21 Static", duration_sec=120)
    stream = StreamUrl(
        url="file:///data/music/static/bed-01.mp3",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    mock_resolve.return_value = stream
    mock_enqueue.return_value = EnqueueResult(city_tags=["moscow"])

    pending = {
        "pending_order_tracks": {
            "bed-01": {
                "track_id": "bed-01",
                "title": "Bed 01",
                "artist": "FM21 Static",
                "duration_sec": 120,
            }
        }
    }
    update, context = _make_update(
        callback_data="order:confirm:bed-01",
        user_data=pending,
    )
    context.user_data["default_city"] = "moscow"

    await order_callback(update, context)

    mock_resolve.assert_awaited_once_with("bed-01")
    mock_enqueue.assert_awaited_once_with(
        uri=stream.url,
        city_tag="moscow",
        title="Bed 01",
        artist="FM21 Static",
        duration_sec=120,
        track_id="bed-01",
    )
    update.callback_query.message.edit_text.assert_awaited()
    assert "добавлен" in update.callback_query.message.edit_text.await_args.args[0].lower()
    assert "pending_order_tracks" not in context.user_data


@pytest.mark.asyncio
@patch("services.bot.handlers.order.enqueue_music_order", new_callable=AsyncMock)
@patch("services.bot.handlers.order.resolve_stream_url", new_callable=AsyncMock)
async def test_order_enqueue_operator_city_only(
    mock_resolve: AsyncMock,
    mock_enqueue: AsyncMock,
    injector_client,
    auth_headers,
    queue_client,
) -> None:
    from services.bot.clients.injector_client import EnqueueResult

    mock_resolve.return_value = StreamUrl(
        url="file:///data/music/static/bed-02.mp3",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    async def _enqueue(**kwargs) -> EnqueueResult:
        payload = {
            "type": "MUSIC_ORDER",
            "uri": kwargs["uri"],
            "city_tag": kwargs["city_tag"],
            "meta": {
                "title": kwargs["title"],
                "artist": kwargs["artist"],
                "duration_sec": kwargs["duration_sec"],
                "track_id": kwargs["track_id"],
            },
        }
        response = injector_client.post(
            "/internal/enqueue", json=payload, headers=auth_headers
        )
        assert response.status_code == 201, response.text
        body = response.json()
        return EnqueueResult(city_tags=body["city_tags"])

    mock_enqueue.side_effect = _enqueue

    pending = {
        "pending_order_tracks": {
            "bed-02": {
                "track_id": "bed-02",
                "title": "Bed 02",
                "artist": "FM21 Static",
                "duration_sec": 150,
            }
        }
    }
    update, context = _make_update(
        callback_data="order:confirm:bed-02",
        user_data=pending,
    )
    context.user_data["default_city"] = "moscow"

    await order_callback(update, context)

    moscow_items = queue_client.list_items("moscow")
    spb_items = queue_client.list_items("spb")
    assert len(moscow_items) == 1
    assert len(spb_items) == 0
    item = moscow_items[0]
    assert item["type"] == "MUSIC_ORDER"
    assert item["priority"] == 50
    assert item["city_tag"] == "moscow"
    assert item["meta"]["track_id"] == "bed-02"


def test_music_order_waits_behind_current_block(queue_client) -> None:
    """Bot enqueues only — playback order is queue priority (AE2 / no-interrupt)."""
    filler = build_queue_item(
        item_type="MUSIC",
        uri="file:///data/music/static/bed-03.mp3",
        city_tag="moscow",
        meta={"title": "Now playing", "artist": "", "duration_sec": 180},
    )
    queue_client.enqueue_item("moscow", filler)

    order = build_queue_item(
        item_type="MUSIC_ORDER",
        uri="file:///data/music/static/bed-01.mp3",
        city_tag="moscow",
        meta={
            "title": "Ordered",
            "artist": "Band",
            "duration_sec": 180,
            "track_id": "bed-01",
        },
    )
    queue_client.enqueue_item("moscow", order)

    items = queue_client.list_items("moscow")
    assert len(items) == 2
    assert {item["type"] for item in items} == {"MUSIC", "MUSIC_ORDER"}
