"""Voice ad intake — duration check, city confirm, transcode, enqueue."""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from services.bot.injector_client import EnqueueFailure, EnqueueResult, enqueue_voice_ad
from services.bot.transcode import TranscodeError, transcode_ogg_to_mp3
from services.geo.cities import DISPLAY_NAMES
from services.bot.handlers.city import build_city_keyboard

logger = logging.getLogger(__name__)

MAX_AD_DURATION_SEC = int(os.environ.get("MAX_AD_DURATION_SEC", "60"))
ADS_DIR = Path(os.environ.get("ADS_DIR", "/data/ads"))

MSG_TOO_LONG = "Слишком длинное сообщение (макс. 60 сек)"
MSG_PROCESSING = "Обрабатываю…"
MSG_TRANSCODE_FAIL = "Не удалось обработать аудио. Попробуйте ещё раз."


def _display_city(tag: str) -> str:
    if tag == "all":
        return "Все города"
    return DISPLAY_NAMES.get(tag, tag)


def _format_success(city_tags: list[str]) -> str:
    names = ", ".join(_display_city(tag) for tag in city_tags)
    return f"Объявление добавлено в очередь: {names}"


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

    context.user_data["pending_voice"] = {
        "file_id": voice.file_id,
        "duration": voice.duration,
    }
    await message.reply_text(
        "Выберите город для объявления:",
        reply_markup=build_city_keyboard(),
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

    status_message = await bot.send_message(chat_id=chat_id, text=MSG_PROCESSING)

    file_id = pending["file_id"]
    duration_sec = int(pending["duration"])
    context.user_data.pop("pending_voice", None)

    ad_id = uuid.uuid4().hex[:12]
    output_path = ADS_DIR / f"{ad_id}.mp3"

    try:
        with tempfile.TemporaryDirectory() as tmp:
            ogg_path = Path(tmp) / "input.ogg"
            tg_file = await bot.get_file(file_id)
            await tg_file.download_to_drive(custom_path=str(ogg_path))
            transcode_ogg_to_mp3(ogg_path, output_path)
    except TranscodeError:
        logger.exception("transcode failed for voice ad")
        await status_message.edit_text(MSG_TRANSCODE_FAIL)
        return
    except Exception:
        logger.exception("failed to download or transcode voice")
        await status_message.edit_text(MSG_TRANSCODE_FAIL)
        return

    uri = f"file://{output_path}"
    result = await enqueue_voice_ad(
        uri=uri,
        city_tag=city_tag,
        duration_sec=duration_sec,
    )

    if isinstance(result, EnqueueResult):
        await status_message.edit_text(_format_success(result.city_tags))
        return

    if result.status_code == 409:
        await status_message.edit_text(_format_queue_full(result.city_tag or city_tag))
        output_path.unlink(missing_ok=True)
        return

    await status_message.edit_text(result.message)
    output_path.unlink(missing_ok=True)
