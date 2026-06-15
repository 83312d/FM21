"""Operator city context and inline confirm callbacks."""

from __future__ import annotations

import logging
import os
import re

from telegram import Update
from telegram.ext import ContextTypes

from services.bot.handlers.conversation import MSG_STALE, consume_pending_voice
from services.bot.storage.operator_prefs import set_default_city
from services.geo.cities import DISPLAY_NAMES
from services.injector.fanout import load_active_cities

logger = logging.getLogger(__name__)

DEFAULT_OPERATOR_CITY = os.environ.get("DEFAULT_OPERATOR_CITY", "moscow")
CITIES_YAML_PATH = os.environ.get("CITIES_YAML_PATH", "broadcast/liquidsoap/cities.yaml")

AD_CALLBACK_PATTERN = re.compile(r"^ad:(?P<city_tag>[a-z_]+)(?::(?P<nonce>[a-f0-9]+))?$")


def _display_city(tag: str) -> str:
    if tag == "all":
        return "Все города"
    return DISPLAY_NAMES.get(tag, tag)


def _active_cities() -> list[str]:
    return load_active_cities(CITIES_YAML_PATH)


def _format_city_choices() -> str:
    tags = [*_active_cities(), "all"]
    return ", ".join(tags)


def get_operator_city(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("default_city", DEFAULT_OPERATOR_CITY)


async def city_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    active = set(_active_cities()) | {"all"}
    if not context.args:
        tag = get_operator_city(context)
        await update.message.reply_text(f"Текущий город по умолчанию: {_display_city(tag)}")
        return

    tag = context.args[0].lower()
    if tag not in active:
        await update.message.reply_text(
            f"Неизвестный город. Используйте: {_format_city_choices()}."
        )
        return

    user_id = update.effective_user.id
    await set_default_city(user_id, tag)
    context.user_data["default_city"] = tag
    await update.message.reply_text(f"Город по умолчанию: {_display_city(tag)}")


async def ad_city_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard tap after voice message."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    match = AD_CALLBACK_PATTERN.match(query.data)
    if not match:
        await query.answer()
        return

    city_tag = match.group("city_tag")
    active = set(_active_cities()) | {"all"}
    if city_tag not in active:
        await query.answer("Неизвестный город", show_alert=True)
        return

    nonce = match.group("nonce")
    if not nonce:
        await query.answer(MSG_STALE, show_alert=True)
        return

    pending = consume_pending_voice(context, nonce=nonce)
    if pending is None:
        await query.answer(MSG_STALE, show_alert=True)
        return

    await query.answer()
    if query.message:
        await query.message.edit_reply_markup(reply_markup=None)

    # Lazy import avoids circular dependency at module load.
    from services.bot.handlers.voice import process_confirmed_voice

    await process_confirmed_voice(update, context, city_tag, pending)


__all__ = ["ad_city_callback", "city_command", "get_operator_city"]
