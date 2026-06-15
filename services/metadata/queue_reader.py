"""Pending queue preview for fm21:queue:{cityTag} (Broadcast Semantics §4, U28)."""

from __future__ import annotations

import json
from typing import Any

import redis
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.geo.cities import CityRegistry
from services.metadata.now_playing import ContentType, _map_content_type

QUEUE_KEY_PREFIX = "fm21:queue:"
PREVIEW_LIMIT = 5

TYPE_PRIORITIES: dict[str, int] = {
    "AD": 100,
    "NEWS_PAIR": 80,
    "MUSIC_ORDER": 50,
    "MUSIC": 10,
}

STINGER_DURATION_SEC = 4


class QueueItemPreview(BaseModel):
    title: str
    artist: str | None = None
    content_type: ContentType
    duration_sec: int


class QueuePreviewResponse(BaseModel):
    city_tag: str
    items: list[QueueItemPreview]


def _item_priority(item: dict[str, Any]) -> int:
    raw = item.get("priority")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    item_type = item.get("type")
    if isinstance(item_type, str):
        return TYPE_PRIORITIES.get(item_type.upper(), 0)
    return 0


def _preview_duration_sec(item: dict[str, Any]) -> int:
    meta = item.get("meta") or {}
    try:
        duration = max(1, int(meta.get("duration_sec", 1)))
    except (TypeError, ValueError):
        duration = 1
    if str(item.get("type", "")).upper() == "NEWS_PAIR":
        try:
            stinger = int(meta.get("stinger_duration_sec", STINGER_DURATION_SEC))
        except (TypeError, ValueError):
            stinger = STINGER_DURATION_SEC
        duration += max(0, stinger)
    return duration


def _to_preview_item(item: dict[str, Any]) -> QueueItemPreview:
    meta = item.get("meta") or {}
    title = str(meta.get("title") or "FM21")
    artist = meta.get("artist") or None
    if artist == "":
        artist = None
    return QueueItemPreview(
        title=title,
        artist=artist,
        content_type=_map_content_type(item.get("type")),
        duration_sec=_preview_duration_sec(item),
    )


def _sort_pending_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(enumerate(items))

    def sort_key(entry: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        idx, item = entry
        return (-_item_priority(item), -idx)

    indexed.sort(key=sort_key)
    return [item for _, item in indexed]


def read_queue_preview(
    client: redis.Redis,
    registry: CityRegistry,
    city_tag: str,
    *,
    limit: int = PREVIEW_LIMIT,
) -> QueuePreviewResponse | JSONResponse:
    if registry.get(city_tag) is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "unknown_city",
                "message": "cityTag is not an active broadcast city",
            },
        )

    raw_items = client.lrange(f"{QUEUE_KEY_PREFIX}{city_tag}", 0, -1)
    decoded: list[dict[str, Any]] = []
    for raw in raw_items:
        try:
            item = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(item, dict):
            decoded.append(item)

    preview = [_to_preview_item(item) for item in _sort_pending_items(decoded)[:limit]]
    return QueuePreviewResponse(city_tag=city_tag, items=preview)
