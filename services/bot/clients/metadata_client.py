"""HTTP client for metadata now-playing and queue preview (U27/U28)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

import httpx

METADATA_URL = os.environ.get("METADATA_URL", "http://metadata:8080")

ContentType = Literal["music", "news", "ad"]


@dataclass(frozen=True)
class NowPlaying:
    title: str
    artist: str | None
    content_type: ContentType
    remaining_sec: int


@dataclass(frozen=True)
class QueueItemPreview:
    title: str
    artist: str | None
    content_type: ContentType
    duration_sec: int


@dataclass(frozen=True)
class QueuePreview:
    city_tag: str
    items: list[QueueItemPreview]


@dataclass(frozen=True)
class MetadataFetchError:
    message: str


async def fetch_now_playing(city_tag: str) -> NowPlaying | None | MetadataFetchError:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{METADATA_URL}/api/now-playing/{city_tag}")
        except httpx.HTTPError:
            return MetadataFetchError(message="Не удалось получить статус эфира. Попробуйте позже.")

    if response.status_code == 404:
        body = response.json()
        if body.get("error") == "not_playing":
            return None
        return MetadataFetchError(message="Не удалось получить статус эфира. Попробуйте позже.")

    if response.status_code != 200:
        return MetadataFetchError(message="Не удалось получить статус эфира. Попробуйте позже.")

    payload = response.json()
    return NowPlaying(
        title=payload["title"],
        artist=payload.get("artist"),
        content_type=payload["content_type"],
        remaining_sec=int(payload.get("remaining_sec", 0)),
    )


async def fetch_queue_preview(city_tag: str) -> QueuePreview | MetadataFetchError:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{METADATA_URL}/api/queue/{city_tag}")
        except httpx.HTTPError:
            return MetadataFetchError(message="Не удалось получить статус эфира. Попробуйте позже.")

    if response.status_code != 200:
        return MetadataFetchError(message="Не удалось получить статус эфира. Попробуйте позже.")

    payload = response.json()
    items = [
        QueueItemPreview(
            title=item["title"],
            artist=item.get("artist"),
            content_type=item["content_type"],
            duration_sec=int(item.get("duration_sec", 0)),
        )
        for item in payload.get("items", [])
    ]
    return QueuePreview(city_tag=payload.get("city_tag", city_tag), items=items)
