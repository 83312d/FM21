"""Bot voice ad flow — U26: confirm mandatory, stale callback, 10m expiry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import CallbackQuery, Chat, Message, Update, User, Voice

from services.bot.clients.ads_client import SubmitFailure, SubmitResult
from services.bot.handlers.city import ad_city_callback
from services.bot.handlers.conversation import (
    MSG_STALE,
    PENDING_VOICE_KEY,
    PENDING_VOICE_TTL_SEC,
    new_pending_voice,
)
from services.bot.handlers.voice import voice_message
from services.bot.keyboards import build_city_keyboard


def _make_voice_update(
    *,
    duration: int = 30,
    file_id: str = "voice-file-1",
    user_id: int = 42,
    user_data: dict | None = None,
) -> tuple[Update, MagicMock]:
    user = User(id=user_id, first_name="Op", is_bot=False)
    chat = Chat(id=100, type="private")
    message = MagicMock(spec=Message)
    message.chat = chat
    message.chat_id = chat.id
    message.reply_text = AsyncMock()
    message.voice = Voice(
        file_id=file_id,
        file_unique_id="uniq-1",
        duration=duration,
    )

    context = MagicMock()
    context.user_data = user_data if user_data is not None else {}

    update = Update(update_id=1, message=message)
    return update, context


def _make_callback_update(
    *,
    callback_data: str,
    user_data: dict | None = None,
) -> tuple[Update, MagicMock]:
    user = User(id=42, first_name="Op", is_bot=False)
    chat = Chat(id=100, type="private")
    message = MagicMock(spec=Message)
    message.chat = chat
    message.chat_id = chat.id
    message.edit_reply_markup = AsyncMock()
    message.edit_text = AsyncMock()

    query = MagicMock(spec=CallbackQuery)
    query.data = callback_data
    query.message = message
    query.answer = AsyncMock()

    context = MagicMock()
    context.user_data = user_data if user_data is not None else {}
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()
    context.bot.get_file = AsyncMock()

    update = Update(update_id=2, callback_query=query)
    update._effective_user = user
    update._effective_chat = chat
    return update, context


@pytest.mark.asyncio
async def test_voice_rejects_over_60_seconds() -> None:
    update, context = _make_voice_update(duration=61)
    await voice_message(update, context)
    update.message.reply_text.assert_awaited_once_with(
        "Слишком длинное сообщение (макс. 60 сек)"
    )
    assert PENDING_VOICE_KEY not in context.user_data


@pytest.mark.asyncio
async def test_voice_accepts_60_seconds() -> None:
    update, context = _make_voice_update(duration=60)
    await voice_message(update, context)
    assert PENDING_VOICE_KEY in context.user_data
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_voice_stores_pending_and_shows_city_keyboard() -> None:
    update, context = _make_voice_update(duration=25, file_id="abc")
    await voice_message(update, context)

    pending = context.user_data[PENDING_VOICE_KEY]
    assert pending["file_id"] == "abc"
    assert pending["duration"] == 25
    assert "nonce" in pending
    assert "created_at" in pending

    markup = update.message.reply_text.await_args.kwargs["reply_markup"]
    assert markup is not None


@pytest.mark.asyncio
async def test_voice_keyboard_embeds_pending_nonce() -> None:
    update, context = _make_voice_update()
    await voice_message(update, context)

    nonce = context.user_data[PENDING_VOICE_KEY]["nonce"]
    markup = update.message.reply_text.await_args.kwargs["reply_markup"]
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]
    assert all(cb.endswith(f":{nonce}") for cb in callbacks)
    assert any(cb.startswith("ad:moscow:") for cb in callbacks)


def test_build_city_keyboard_with_nonce() -> None:
    markup = build_city_keyboard(nonce="deadbeef")
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]
    assert callbacks[-1] == "ad:all:deadbeef"


@pytest.mark.asyncio
@patch("services.bot.handlers.voice.submit_voice_ad", new_callable=AsyncMock)
async def test_city_confirm_submits_via_ads_client(mock_submit: AsyncMock) -> None:
    mock_submit.return_value = SubmitResult(city_tags=["moscow"])

    pending = new_pending_voice(file_id="file-99", duration=40)
    nonce = pending["nonce"]
    update, context = _make_callback_update(
        callback_data=f"ad:moscow:{nonce}",
        user_data={PENDING_VOICE_KEY: pending},
    )

    tg_file = MagicMock()
    tg_file.download_to_drive = AsyncMock()
    context.bot.get_file.return_value = tg_file

    status_msg = MagicMock()
    status_msg.edit_text = AsyncMock()
    context.bot.send_message.return_value = status_msg

    await ad_city_callback(update, context)

    mock_submit.assert_awaited_once()
    assert mock_submit.await_args.kwargs["city_tag"] == "moscow"
    assert mock_submit.await_args.kwargs["telegram_user_id"] == 42
    assert mock_submit.await_args.kwargs["duration_sec"] == 40
    assert PENDING_VOICE_KEY not in context.user_data
    status_msg.edit_text.assert_awaited()
    success_text = status_msg.edit_text.await_args.args[0]
    assert "добавлено" in success_text.lower()
    assert "Слушайте: http://localhost:8080/?city=moscow" in success_text


@pytest.mark.asyncio
async def test_stale_callback_when_no_pending() -> None:
    update, context = _make_callback_update(callback_data="ad:moscow:abc12345")
    await ad_city_callback(update, context)
    update.callback_query.answer.assert_awaited_once_with(MSG_STALE, show_alert=True)


@pytest.mark.asyncio
async def test_stale_callback_wrong_nonce() -> None:
    pending = new_pending_voice(file_id="f", duration=10)
    wrong_nonce = "00000000" if pending["nonce"] != "00000000" else "ffffffff"
    update, context = _make_callback_update(
        callback_data=f"ad:moscow:{wrong_nonce}",
        user_data={PENDING_VOICE_KEY: pending},
    )
    await ad_city_callback(update, context)
    update.callback_query.answer.assert_awaited_once_with(MSG_STALE, show_alert=True)
    assert PENDING_VOICE_KEY in context.user_data


@pytest.mark.asyncio
@patch("services.bot.handlers.conversation.time.monotonic")
async def test_expired_pending_rejected(mock_monotonic: MagicMock) -> None:
    base = 1000.0
    mock_monotonic.return_value = base + PENDING_VOICE_TTL_SEC + 1

    pending = new_pending_voice(file_id="f", duration=10)
    pending["created_at"] = base
    update, context = _make_callback_update(
        callback_data=f"ad:spb:{pending['nonce']}",
        user_data={PENDING_VOICE_KEY: pending},
    )
    await ad_city_callback(update, context)
    update.callback_query.answer.assert_awaited_once_with(MSG_STALE, show_alert=True)
    assert PENDING_VOICE_KEY not in context.user_data


@pytest.mark.asyncio
@patch("services.bot.handlers.voice.submit_voice_ad", new_callable=AsyncMock)
async def test_queue_full_409_surfaces_message(mock_submit: AsyncMock) -> None:
    mock_submit.return_value = SubmitFailure(
        status_code=409,
        message="Очередь объявлений для Москва заполнена",
        city_tag="moscow",
    )

    pending = new_pending_voice(file_id="f", duration=20)
    update, context = _make_callback_update(
        callback_data=f"ad:moscow:{pending['nonce']}",
        user_data={PENDING_VOICE_KEY: pending},
    )
    tg_file = MagicMock()
    tg_file.download_to_drive = AsyncMock()
    context.bot.get_file.return_value = tg_file
    status_msg = MagicMock()
    status_msg.edit_text = AsyncMock()
    context.bot.send_message.return_value = status_msg

    await ad_city_callback(update, context)

    status_msg.edit_text.assert_awaited()
    assert "заполнена" in status_msg.edit_text.await_args.args[0].lower()
    assert PENDING_VOICE_KEY in context.user_data


@pytest.mark.asyncio
@patch("services.bot.handlers.voice.submit_voice_ad", new_callable=AsyncMock)
async def test_double_tap_submits_only_once(mock_submit: AsyncMock) -> None:
    mock_submit.return_value = SubmitResult(city_tags=["moscow"])

    pending = new_pending_voice(file_id="f", duration=20)
    nonce = pending["nonce"]
    user_data = {PENDING_VOICE_KEY: pending}

    tg_file = MagicMock()
    tg_file.download_to_drive = AsyncMock()

    for _ in range(2):
        update, context = _make_callback_update(
            callback_data=f"ad:moscow:{nonce}",
            user_data=user_data,
        )
        context.bot.get_file.return_value = tg_file
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        context.bot.send_message.return_value = status_msg
        update.callback_query.answer = AsyncMock()
        await ad_city_callback(update, context)

    mock_submit.assert_awaited_once()


@pytest.mark.asyncio
@patch("services.bot.handlers.voice.submit_voice_ad", new_callable=AsyncMock)
async def test_new_voice_invalidates_previous_nonce(mock_submit: AsyncMock) -> None:
    mock_submit.return_value = SubmitResult(city_tags=["moscow"])

    old_pending = new_pending_voice(file_id="old", duration=15)
    old_nonce = old_pending["nonce"]

    update1, context = _make_voice_update(user_data={PENDING_VOICE_KEY: old_pending})
    await voice_message(update1, context)

    new_nonce = context.user_data[PENDING_VOICE_KEY]["nonce"]
    assert new_nonce != old_nonce

    update2, _ = _make_callback_update(
        callback_data=f"ad:moscow:{old_nonce}",
        user_data=context.user_data,
    )
    update2.callback_query.answer = AsyncMock()
    await ad_city_callback(update2, context)
    update2.callback_query.answer.assert_awaited_once_with(MSG_STALE, show_alert=True)
    mock_submit.assert_not_awaited()
