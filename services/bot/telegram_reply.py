"""Resilient Telegram message helpers — RetryAfter sleep+retry, fallback on error."""

from __future__ import annotations

import asyncio
import logging

from telegram import Message
from telegram.error import RetryAfter, TelegramError

logger = logging.getLogger(__name__)


async def safe_reply(message: Message, text: str, **kwargs) -> Message | None:
    """Reply to a message; retry after flood control; fallback to chat.send_message."""
    try:
        return await message.reply_text(text, **kwargs)
    except RetryAfter as exc:
        await asyncio.sleep(exc.retry_after + 0.5)
        try:
            return await message.reply_text(text, **kwargs)
        except TelegramError:
            logger.warning("reply_text failed after RetryAfter, sending new message")
            return await message.chat.send_message(text, **kwargs)
    except TelegramError:
        logger.warning("reply_text failed, sending new message")
        return await message.chat.send_message(text, **kwargs)


async def safe_edit(message: Message, text: str, **kwargs) -> Message | None:
    """Edit a message; retry after flood control; fallback to chat.send_message."""
    try:
        return await message.edit_text(text, **kwargs)
    except RetryAfter as exc:
        await asyncio.sleep(exc.retry_after + 0.5)
        try:
            return await message.edit_text(text, **kwargs)
        except TelegramError:
            logger.warning("edit_text failed after RetryAfter, sending new message")
            return await message.chat.send_message(text, **kwargs)
    except TelegramError:
        logger.warning("edit_text failed, sending new message")
        return await message.chat.send_message(text, **kwargs)
