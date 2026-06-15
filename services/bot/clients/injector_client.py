"""HTTP client for injector POST /internal/enqueue."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

INJECTOR_URL = os.environ.get("INJECTOR_URL", "http://injector:8080")
INTERNAL_TOKEN = os.environ.get("INTERNAL_ENQUEUE_TOKEN", "")


@dataclass(frozen=True)
class EnqueueResult:
    city_tags: list[str]


@dataclass(frozen=True)
class EnqueueFailure:
    status_code: int
    message: str
    city_tag: str | None = None


async def _post_enqueue(payload: dict) -> EnqueueResult | EnqueueFailure:
    headers = {"X-FM21-Internal-Token": INTERNAL_TOKEN}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{INJECTOR_URL}/internal/enqueue",
            json=payload,
            headers=headers,
        )

    if response.status_code == 201:
        body = response.json()
        city_tag = payload["city_tag"]
        return EnqueueResult(city_tags=body.get("city_tags", [city_tag]))

    message = "Не удалось добавить в очередь."
    city: str | None = None
    try:
        detail = response.json().get("detail")
        if isinstance(detail, dict):
            message = detail.get("message", message)
            city = detail.get("city_tag")
        elif isinstance(detail, str):
            message = detail
    except (ValueError, AttributeError):
        pass

    return EnqueueFailure(
        status_code=response.status_code,
        message=message,
        city_tag=city,
    )


async def enqueue_music_order(
    *,
    uri: str,
    city_tag: str,
    title: str,
    artist: str,
    duration_sec: int,
    track_id: str,
) -> EnqueueResult | EnqueueFailure:
    payload = {
        "type": "MUSIC_ORDER",
        "uri": uri,
        "city_tag": city_tag,
        "meta": {
            "title": title,
            "artist": artist,
            "duration_sec": duration_sec,
            "track_id": track_id,
        },
    }
    return await _post_enqueue(payload)
