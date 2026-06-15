"""Tests for resilient Telegram reply/edit helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Chat, Message
from telegram.error import RetryAfter, TelegramError

from services.bot.telegram_reply import safe_edit, safe_reply


def _make_message() -> MagicMock:
    chat = MagicMock(spec=Chat)
    chat.send_message = AsyncMock(return_value=MagicMock(spec=Message))
    message = MagicMock(spec=Message)
    message.chat = chat
    message.reply_text = AsyncMock(return_value=message)
    message.edit_text = AsyncMock(return_value=message)
    return message


@pytest.mark.asyncio
@patch("services.bot.telegram_reply.asyncio.sleep", new_callable=AsyncMock)
async def test_safe_reply_retries_after_retry_after(mock_sleep: AsyncMock) -> None:
    message = _make_message()
    message.reply_text.side_effect = [RetryAfter(2), message]

    result = await safe_reply(message, "hello")

    mock_sleep.assert_awaited_once_with(2.5)
    assert message.reply_text.await_count == 2
    assert result is message


@pytest.mark.asyncio
@patch("services.bot.telegram_reply.asyncio.sleep", new_callable=AsyncMock)
async def test_safe_reply_falls_back_after_retry_after_then_error(
    mock_sleep: AsyncMock,
) -> None:
    message = _make_message()
    fallback = MagicMock(spec=Message)
    message.reply_text.side_effect = [RetryAfter(1), TelegramError("flood")]
    message.chat.send_message.return_value = fallback

    result = await safe_reply(message, "hello", parse_mode="HTML")

    mock_sleep.assert_awaited_once_with(1.5)
    message.chat.send_message.assert_awaited_once_with("hello", parse_mode="HTML")
    assert result is fallback


@pytest.mark.asyncio
async def test_safe_reply_falls_back_on_telegram_error() -> None:
    message = _make_message()
    fallback = MagicMock(spec=Message)
    message.reply_text.side_effect = TelegramError("blocked")
    message.chat.send_message.return_value = fallback

    result = await safe_reply(message, "status")

    message.reply_text.assert_awaited_once_with("status")
    message.chat.send_message.assert_awaited_once_with("status")
    assert result is fallback


@pytest.mark.asyncio
@patch("services.bot.telegram_reply.asyncio.sleep", new_callable=AsyncMock)
async def test_safe_edit_retries_after_retry_after(mock_sleep: AsyncMock) -> None:
    message = _make_message()
    message.edit_text.side_effect = [RetryAfter(3), message]

    result = await safe_edit(message, "updated")

    mock_sleep.assert_awaited_once_with(3.5)
    assert message.edit_text.await_count == 2
    assert result is message


@pytest.mark.asyncio
async def test_safe_edit_falls_back_on_telegram_error() -> None:
    message = _make_message()
    fallback = MagicMock(spec=Message)
    message.edit_text.side_effect = TelegramError("cant edit")
    message.chat.send_message.return_value = fallback

    result = await safe_edit(message, "updated", reply_markup=None)

    message.edit_text.assert_awaited_once_with("updated", reply_markup=None)
    message.chat.send_message.assert_awaited_once_with("updated", reply_markup=None)
    assert result is fallback
