"""Voice ad intake — duration check, city confirm, submit to ads service."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from services.bot.clients.ads_client import SubmitFailure, SubmitResult, submit_voice_ad
from services.bot.handlers.conversation import (
    new_pending_voice,
    store_pending_voice,
)
from services.bot.keyboards import build_city_keyboard
from services.bot.telegram_reply import safe_edit
from services.geo.cities import DISPLAY_NAMES

logger = logging.getLogger(__name__)

MAX_AD_DURATION_SEC = int(os.environ.get("MAX_AD_DURATION_SEC", "60"))
LISTENER_BASE_URL = os.environ.get("LISTENER_BASE_URL", "http://localhost:8080").rstrip("/")

MSG_TOO_LONG = "Слишком длинное сообщение (макс. 60 сек)"
MSG_PROCESSING = "Обрабатываю…"
MSG_TRANSCODE_FAIL = "Не удалось обработать аудио. Попробуйте ещё раз."
MSG_ADS_UNAVAILABLE = "Сервис объявлений недоступен. Попробуйте через минуту."


def _display_city(tag: str) -> str:
    if tag == "all":
        return "Все города"
    return DISPLAY_NAMES.get(tag, tag)


def _format_success(city_tags: list[str]) -> str:
    names = ", ".join(_display_city(tag) for tag in city_tags)
    lines = [f"Объявление добавлено в очередь: {names}"]
    for tag in city_tags:
        lines.append(f"Слушайте: {LISTENER_BASE_URL}/?city={tag}")
    return "\n".join(lines)


def _format_queue_full(city_tag: str | None) -> str:
    if city_tag:
        return f"Очередь объявлений для {_display_city(city_tag)} заполнена"
    return "Очередь объявлений заполнена"


async def voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None or message.voice is None:
        return

    voice = message.voice
    if voice.duration > MAX_AD_DURATION_SEC:
        await message.reply_text(MSG_TOO_LONG)
        return

    pending = new_pending_voice(file_id=voice.file_id, duration=voice.duration)
    store_pending_voice(context, pending)
    await message.reply_text(
        "Выберите город для объявления:",
        reply_markup=build_city_keyboard(nonce=pending["nonce"]),
    )


async def process_confirmed_voice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    city_tag: str,
    pending: dict[str, Any],
) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id if query and query.message else update.effective_chat.id
    bot = context.bot
    user = update.effective_user

    status_message = await bot.send_message(chat_id=chat_id, text=MSG_PROCESSING)

    file_id = pending["file_id"]
    duration_sec = int(pending["duration"])
    telegram_user_id = user.id if user is not None else 0

    try:
        with tempfile.TemporaryDirectory() as tmp:
            ogg_path = Path(tmp) / "input.ogg"
            tg_file = await bot.get_file(file_id)
            await tg_file.download_to_drive(custom_path=str(ogg_path))
            result = await submit_voice_ad(
                ogg_path,
                telegram_user_id=telegram_user_id,
                city_tag=city_tag,
                duration_sec=duration_sec,
            )
    except httpx.ConnectError:
        logger.exception("ads service unreachable for voice ad")
        await safe_edit(status_message, MSG_ADS_UNAVAILABLE)
        return
    except Exception:
        logger.exception("failed to download or submit voice ad")
        await safe_edit(status_message, MSG_TRANSCODE_FAIL)
        return

    if isinstance(result, SubmitResult):
        await safe_edit(status_message, _format_success(result.city_tags))
        return

    if result.status_code == 409:
        restored = new_pending_voice(file_id=file_id, duration=duration_sec)
        store_pending_voice(context, restored)
        await safe_edit(
            status_message,
            f"{_format_queue_full(result.city_tag or city_tag)}\n"
            "Нажмите город ещё раз или отправьте голосовое заново.",
            reply_markup=build_city_keyboard(nonce=restored["nonce"]),
        )
        return

    if result.status_code == 422:
        await safe_edit(status_message, MSG_TRANSCODE_FAIL)
        return

    await safe_edit(status_message, result.message)
