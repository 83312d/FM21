"""Bot /status — partial U23: next news slot countdown from UTC slot clock."""

from __future__ import annotations

from datetime import UTC, datetime

from telegram import Update
from telegram.ext import ContextTypes

from services.bot.handlers.city import get_operator_city
from services.geo.cities import DISPLAY_NAMES
from services.news.slot_clock import next_news_at, seconds_until_next_news


def _display_city(tag: str) -> str:
    if tag == "all":
        return "все города"
    return DISPLAY_NAMES.get(tag, tag)


def format_countdown(seconds: float) -> str:
    total = int(seconds)
    if total <= 0:
        return "сейчас"
    minutes, secs = divmod(total, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        if minutes:
            return f"{hours} ч {minutes} мин"
        return f"{hours} ч"
    if minutes > 0:
        if secs:
            return f"{minutes} мин {secs} сек"
        return f"{minutes} мин"
    return f"{secs} сек"


def format_status_message(
    *,
    city_tag: str,
    now: datetime | None = None,
) -> str:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    nxt = next_news_at(current)
    countdown = format_countdown(seconds_until_next_news(current))
    slot_label = nxt.strftime("%H:%M UTC")
    city_label = _display_city(city_tag)
    return (
        f"Следующие новости ({city_label}): {slot_label} ({countdown})"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    city_tag = get_operator_city(context)
    await update.message.reply_text(
        format_status_message(city_tag=city_tag),
    )
