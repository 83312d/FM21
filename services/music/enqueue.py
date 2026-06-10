"""HTTP client for injector MUSIC enqueue (U12)."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

INJECTOR_URL = os.environ.get("INJECTOR_URL", "http://injector:8080")


def _internal_token() -> str:
    return os.environ.get("INTERNAL_ENQUEUE_TOKEN", "")


@dataclass(frozen=True)
class MusicEnqueueResult:
    id: str
    city_tags: list[str]


@dataclass(frozen=True)
class MusicEnqueueFailure:
    status_code: int
    message: str
    city_tag: str | None = None


async def enqueue_music(
    *,
    uri: str,
    city_tag: str,
    title: str,
    artist: str,
    duration_sec: int,
    track_id: str = "",
    item_type: str = "MUSIC",
) -> MusicEnqueueResult | MusicEnqueueFailure:
    payload = {
        "type": item_type,
        "uri": uri,
        "city_tag": city_tag,
        "meta": {
            "title": title,
            "artist": artist,
            "duration_sec": duration_sec,
            "track_id": track_id,
        },
    }
    headers = {"X-FM21-Internal-Token": _internal_token()}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{INJECTOR_URL}/internal/enqueue",
            json=payload,
            headers=headers,
        )

    if response.status_code == 201:
        body = response.json()
        return MusicEnqueueResult(id=body["id"], city_tags=body.get("city_tags", [city_tag]))

    message = "Failed to enqueue music item."
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

    return MusicEnqueueFailure(
        status_code=response.status_code,
        message=message,
        city_tag=city,
    )
