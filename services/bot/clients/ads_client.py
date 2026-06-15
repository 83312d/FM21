"""HTTP client for ads service POST /internal/ads/submit."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import httpx

ADS_URL = os.environ.get("ADS_URL", "http://ads:8080")
INTERNAL_TOKEN = os.environ.get("INTERNAL_ENQUEUE_TOKEN", "")


@dataclass(frozen=True)
class SubmitResult:
    city_tags: list[str]


@dataclass(frozen=True)
class SubmitFailure:
    status_code: int
    message: str
    city_tag: str | None = None


async def submit_voice_ad(
    ogg_path: Path,
    *,
    telegram_user_id: int,
    city_tag: str,
    duration_sec: int,
) -> SubmitResult | SubmitFailure:
    headers = {"X-FM21-Internal-Token": INTERNAL_TOKEN}
    data = {
        "telegram_user_id": str(telegram_user_id),
        "city_tag": city_tag,
        "duration_sec": str(duration_sec),
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        with ogg_path.open("rb") as audio_file:
            response = await client.post(
                f"{ADS_URL}/internal/ads/submit",
                headers=headers,
                data=data,
                files={"audio": ("voice.ogg", audio_file, "audio/ogg")},
            )

    if response.status_code == 201:
        body = response.json()
        return SubmitResult(city_tags=body.get("city_tags", [city_tag]))

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

    return SubmitFailure(
        status_code=response.status_code,
        message=message,
        city_tag=city,
    )
