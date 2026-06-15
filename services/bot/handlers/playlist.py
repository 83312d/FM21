"""Bot /playlist — admin-only playlist policy override (U27)."""

from __future__ import annotations

import re

from telegram import Update
from telegram.ext import ContextTypes

from services.bot.handlers.city import get_operator_city
from services.bot.middleware.auth import is_admin
from services.bot.storage.playlist_config import upsert_city_playlist
from services.geo.cities import DISPLAY_NAMES

_PLAYLIST_ID_RE = re.compile(r"^\d+:\d+$")

MSG_USAGE = "Используйте: /playlist <uid:kind> (например 1904216019:1001)"
MSG_ADMIN_ONLY = "Команда доступна только администраторам."
MSG_INVALID_NAME = "Неверный формат плейлиста. Ожидается uid:kind, например 1904216019:1001."
MSG_CITY_ALL = "Смена плейлиста доступна для одного города. Укажите город: /city moscow"


def _display_city(tag: str) -> str:
    return DISPLAY_NAMES.get(tag, tag)


def parse_playlist_name(args: list[str]) -> str | None:
    if len(args) != 1:
        return None
    name = args[0].strip()
    if not _PLAYLIST_ID_RE.match(name):
        return None
    return name


async def playlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    if not is_admin(update.effective_user.id):
        await update.message.reply_text(MSG_ADMIN_ONLY)
        return

    playlist_id = parse_playlist_name(context.args)
    if playlist_id is None:
        await update.message.reply_text(MSG_USAGE if not context.args else MSG_INVALID_NAME)
        return

    city_tag = get_operator_city(context)
    if city_tag == "all":
        await update.message.reply_text(MSG_CITY_ALL)
        return

    await upsert_city_playlist(city_tag, playlist_id)
    city_label = _display_city(city_tag)
    await update.message.reply_text(
        f"Плейлист для {city_label} обновлён: {playlist_id}"
    )
