"""Operator/admin allowlists and per-user prefs bootstrap."""

from __future__ import annotations

import logging
import os

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from services.bot.storage.operator_prefs import get_stored_default_city
from services.injector.fanout import load_active_cities

logger = logging.getLogger(__name__)

MSG_ACCESS_DENIED = "Доступ запрещён."
CITIES_YAML_PATH = os.environ.get("CITIES_YAML_PATH", "broadcast/liquidsoap/cities.yaml")
DEFAULT_OPERATOR_CITY = os.environ.get("DEFAULT_OPERATOR_CITY", "moscow")


def _open_access_enabled() -> bool:
    return os.environ.get("BOT_OPEN_ACCESS", "").strip() == "1"


def _parse_allowlist(env_name: str) -> frozenset[int] | None:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return None
    ids: list[int] = []
    for part in raw.split(","):
        piece = part.strip()
        if not piece:
            continue
        try:
            ids.append(int(piece))
        except ValueError:
            logger.error("invalid %s entry (expected integer): %r", env_name, piece)
            raise
    return frozenset(ids)


def is_operator(user_id: int) -> bool:
    operators = _parse_allowlist("TELEGRAM_OPERATOR_IDS")
    admins = _parse_allowlist("TELEGRAM_ADMIN_IDS") or frozenset()
    if user_id in admins:
        return True
    if operators is not None:
        return user_id in operators
    return _open_access_enabled()


def is_admin(user_id: int) -> bool:
    admins = _parse_allowlist("TELEGRAM_ADMIN_IDS")
    if admins is None:
        return False
    return user_id in admins


def _valid_city_tag(tag: str) -> bool:
    if tag == "all":
        return True
    try:
        active = load_active_cities(CITIES_YAML_PATH)
    except OSError:
        logger.warning("could not load cities.yaml for prefs validation")
        return True
    return tag in active


async def ensure_operator_city_loaded(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_user_id: int,
) -> None:
    if "default_city" in context.user_data:
        return
    stored = await get_stored_default_city(telegram_user_id)
    if stored is not None and _valid_city_tag(stored):
        context.user_data["default_city"] = stored
        return
    if stored is not None and not _valid_city_tag(stored):
        logger.warning(
            "operator %s has invalid stored city %r; using default",
            telegram_user_id,
            stored,
        )
    context.user_data["default_city"] = DEFAULT_OPERATOR_CITY


async def auth_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        raise ApplicationHandlerStop()

    if not is_operator(user.id):
        if update.callback_query is not None:
            await update.callback_query.answer(MSG_ACCESS_DENIED, show_alert=True)
        elif update.effective_message is not None:
            await update.effective_message.reply_text(MSG_ACCESS_DENIED)
        raise ApplicationHandlerStop()

    await ensure_operator_city_loaded(context, user.id)
