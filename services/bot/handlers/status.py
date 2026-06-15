"""Bot /status — now-playing, queue preview, next news (U27)."""

from __future__ import annotations

from datetime import UTC, datetime

from telegram import Update
from telegram.ext import ContextTypes

from services.bot.clients.metadata_client import (
    MetadataFetchError,
    NowPlaying,
    QueuePreview,
    fetch_now_playing,
    fetch_queue_preview,
)
from services.bot.handlers.city import get_operator_city
from services.bot.telegram_reply import safe_reply
from services.geo.cities import DISPLAY_NAMES
from services.news.slot_clock import next_news_at, seconds_until_next_news

MSG_CITY_ALL = "Статус эфира доступен для одного города. Укажите город: /city moscow"
MSG_FETCH_ERROR = "Не удалось получить статус эфира. Попробуйте позже."

_CONTENT_LABELS = {
    "music": "музыка",
    "ad": "реклама",
    "news": "новости",
}


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


def _format_track_line(
    *,
    title: str,
    artist: str | None,
    content_type: str,
    duration_hint: str,
) -> str:
    label = _CONTENT_LABELS.get(content_type, content_type)
    if artist:
        return f"• {title} — {artist} ({label}, {duration_hint})"
    return f"• {title} ({label}, {duration_hint})"


def _format_now_playing(now_playing: NowPlaying | None) -> str:
    if now_playing is None:
        return "Сейчас в эфире: нет данных"
    remaining = format_countdown(now_playing.remaining_sec)
    line = _format_track_line(
        title=now_playing.title,
        artist=now_playing.artist,
        content_type=now_playing.content_type,
        duration_hint=f"осталось {remaining}",
    )
    return f"Сейчас в эфире:\n{line}"


def _format_queue(queue: QueuePreview) -> str:
    if not queue.items:
        return "Очередь пуста"
    lines = [
        _format_track_line(
            title=item.title,
            artist=item.artist,
            content_type=item.content_type,
            duration_hint=f"{item.duration_sec} сек",
        )
        for item in queue.items
    ]
    return "Далее в очереди:\n" + "\n".join(lines)


def format_status_message(
    *,
    city_tag: str,
    now_playing: NowPlaying | None = None,
    queue: QueuePreview | None = None,
    now: datetime | None = None,
) -> str:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    nxt = next_news_at(current)
    countdown = format_countdown(seconds_until_next_news(current))
    slot_label = nxt.strftime("%H:%M UTC")
    city_label = _display_city(city_tag)

    sections = [f"Статус ({city_label})"]
    if now_playing is not None or queue is not None:
        sections.append(_format_now_playing(now_playing))
        sections.append(_format_queue(queue or QueuePreview(city_tag=city_tag, items=[])))
    sections.append(f"Следующие новости: {slot_label} ({countdown})")
    return "\n\n".join(sections)


async def fetch_status(city_tag: str) -> str:
    now_playing = await fetch_now_playing(city_tag)
    if isinstance(now_playing, MetadataFetchError):
        return now_playing.message

    queue = await fetch_queue_preview(city_tag)
    if isinstance(queue, MetadataFetchError):
        return queue.message

    return format_status_message(
        city_tag=city_tag,
        now_playing=now_playing,
        queue=queue,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    city_tag = get_operator_city(context)
    if city_tag == "all":
        await safe_reply(update.message, MSG_CITY_ALL)
        return

    text = await fetch_status(city_tag)
    await safe_reply(update.message, text)
