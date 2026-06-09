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


async def enqueue_voice_ad(
    *,
    uri: str,
    city_tag: str,
    duration_sec: int,
) -> EnqueueResult | EnqueueFailure:
    payload = {
        "type": "AD",
        "uri": uri,
        "city_tag": city_tag,
        "meta": {
            "title": "Voice ad",
            "artist": "",
            "duration_sec": duration_sec,
        },
    }
    headers = {"X-FM21-Internal-Token": INTERNAL_TOKEN}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{INJECTOR_URL}/internal/enqueue",
            json=payload,
            headers=headers,
        )

    if response.status_code == 201:
        body = response.json()
        return EnqueueResult(city_tags=body.get("city_tags", [city_tag]))

    message = "Не удалось добавить объявление в очередь."
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
