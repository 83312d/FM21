"""Bot /order — search, confirm, enqueue MUSIC_ORDER."""

from __future__ import annotations

import logging
import re
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.bot.clients.injector_client import EnqueueFailure, EnqueueResult, enqueue_music_order
from services.bot.clients.music_client import resolve_stream_url, search_tracks
from services.bot.handlers.city import get_operator_city
from services.bot.parsers.order import format_search_query, parse_order_args
from services.geo.cities import DISPLAY_NAMES
from services.music.provider import TrackInfo

logger = logging.getLogger(__name__)

ORDER_CALLBACK_PATTERN = re.compile(
    r"^order:(?P<action>select|confirm|cancel)(?::(?P<track_id>[^:]+))?$"
)

MSG_USAGE = "Используйте: /order Название — Исполнитель"
MSG_NO_RESULTS = "Ничего не найдено. Попробуйте другое название или исполнителя."
MSG_CITY_ALL = "Заказ музыки доступен для одного города. Укажите город: /city moscow"
MSG_STALE = "Заказ устарел. Отправьте /order снова."
MSG_CANCELLED = "Заказ отменён."
MSG_RESOLVE_FAIL = "Не удалось получить ссылку на трек. Попробуйте позже."
MSG_ENQUEUE_FAIL = "Не удалось добавить трек в очередь."

DEFAULT_DURATION_SEC = 180
SEARCH_LIMIT = 3
PENDING_ORDER_KEY = "pending_order_tracks"


def _display_city(tag: str) -> str:
    return DISPLAY_NAMES.get(tag, tag)


def _track_label(track: TrackInfo) -> str:
    return f"{track.title} — {track.artist}"


def _track_to_dict(track: TrackInfo) -> dict[str, Any]:
    return {
        "track_id": track.track_id,
        "title": track.title,
        "artist": track.artist,
        "duration_sec": track.duration_sec,
    }


def _track_from_dict(data: dict[str, Any]) -> TrackInfo:
    return TrackInfo(
        track_id=data["track_id"],
        title=data["title"],
        artist=data["artist"],
        duration_sec=data.get("duration_sec"),
    )


def _search_keyboard(tracks: list[TrackInfo]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(_track_label(track), callback_data=f"order:select:{track.track_id}")]
        for track in tracks
    ]
    rows.append([InlineKeyboardButton("Отмена", callback_data="order:cancel")])
    return InlineKeyboardMarkup(rows)


def _confirm_keyboard(track_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Добавить в очередь", callback_data=f"order:confirm:{track_id}")],
            [InlineKeyboardButton("Отмена", callback_data="order:cancel")],
        ]
    )


def _store_pending_tracks(context: ContextTypes.DEFAULT_TYPE, tracks: list[TrackInfo]) -> None:
    context.user_data[PENDING_ORDER_KEY] = {
        track.track_id: _track_to_dict(track) for track in tracks
    }


def _get_pending_track(context: ContextTypes.DEFAULT_TYPE, track_id: str) -> TrackInfo | None:
    pending = context.user_data.get(PENDING_ORDER_KEY) or {}
    data = pending.get(track_id)
    if not data:
        return None
    return _track_from_dict(data)


def _clear_pending_tracks(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(PENDING_ORDER_KEY, None)


async def order_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return

    parsed = parse_order_args(context.args or [])
    if parsed is None:
        await message.reply_text(MSG_USAGE)
        return

    city_tag = get_operator_city(context)
    if city_tag == "all":
        await message.reply_text(MSG_CITY_ALL)
        return

    title, artist = parsed
    query = format_search_query(title, artist)

    try:
        tracks = await search_tracks(query, limit=SEARCH_LIMIT)
    except Exception:
        logger.exception("music search failed for /order")
        await message.reply_text(MSG_NO_RESULTS)
        return

    if not tracks:
        await message.reply_text(MSG_NO_RESULTS)
        return

    _store_pending_tracks(context, tracks)
    await message.reply_text(
        "Выберите трек:",
        reply_markup=_search_keyboard(tracks),
    )


async def order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return

    match = ORDER_CALLBACK_PATTERN.match(query.data)
    if not match:
        await query.answer()
        return

    action = match.group("action")
    track_id = match.group("track_id")

    if action == "cancel":
        _clear_pending_tracks(context)
        await query.answer()
        if query.message:
            await query.message.edit_text(MSG_CANCELLED, reply_markup=None)
        return

    if action == "select":
        if not track_id:
            await query.answer(MSG_STALE, show_alert=True)
            return
        track = _get_pending_track(context, track_id)
        if track is None:
            await query.answer(MSG_STALE, show_alert=True)
            return
        await query.answer()
        if query.message:
            await query.message.edit_text(
                f"{_track_label(track)}\n\nДобавить в очередь для {_display_city(get_operator_city(context))}?",
                reply_markup=_confirm_keyboard(track.track_id),
            )
        return

    if action == "confirm":
        if not track_id:
            await query.answer(MSG_STALE, show_alert=True)
            return
        track = _get_pending_track(context, track_id)
        if track is None:
            await query.answer(MSG_STALE, show_alert=True)
            return

        city_tag = get_operator_city(context)
        if city_tag == "all":
            await query.answer(MSG_CITY_ALL, show_alert=True)
            return

        await query.answer()
        if query.message:
            await query.message.edit_reply_markup(reply_markup=None)

        try:
            stream = await resolve_stream_url(track.track_id)
        except Exception:
            logger.exception("stream resolution failed for track %s", track.track_id)
            if query.message:
                await query.message.edit_text(MSG_RESOLVE_FAIL)
            _clear_pending_tracks(context)
            return

        duration_sec = track.duration_sec or DEFAULT_DURATION_SEC
        result = await enqueue_music_order(
            uri=stream.url,
            city_tag=city_tag,
            title=track.title,
            artist=track.artist,
            duration_sec=duration_sec,
            track_id=track.track_id,
        )
        _clear_pending_tracks(context)

        if isinstance(result, EnqueueResult):
            city_name = _display_city(result.city_tags[0])
            if query.message:
                await query.message.edit_text(
                    f"Трек добавлен в очередь: {_track_label(track)} ({city_name})"
                )
            return

        if query.message:
            await query.message.edit_text(result.message or MSG_ENQUEUE_FAIL)
