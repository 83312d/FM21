"""HTTP client for injector POST /internal/enqueue (AD type)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

INJECTOR_URL = os.environ.get("INJECTOR_URL", "http://injector:8080")


@dataclass(frozen=True)
class EnqueueResult:
    city_tags: list[str]


@dataclass(frozen=True)
class EnqueueFailure:
    status_code: int
    message: str
    city_tag: str | None = None
    ambiguous: bool = False


def _internal_token() -> str:
    return os.environ.get("INTERNAL_ENQUEUE_TOKEN", "")


async def enqueue_ad(
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
    headers = {"X-FM21-Internal-Token": _internal_token()}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{INJECTOR_URL}/internal/enqueue",
                json=payload,
                headers=headers,
            )
    except httpx.ConnectError as exc:
        logger.warning("injector unreachable: %s", exc)
        return EnqueueFailure(
            status_code=503,
            message=f"Injector unreachable: {exc}",
        )
    except httpx.HTTPError as exc:
        logger.warning("injector enqueue request failed: %s", exc)
        return EnqueueFailure(
            status_code=502,
            message=f"Injector request failed: {exc}",
            ambiguous=True,
        )

    if response.status_code == 201:
        try:
            body = response.json()
            city_tags = body.get("city_tags", [city_tag])
        except ValueError as exc:
            logger.warning("injector returned 201 with invalid JSON: %s", exc)
            return EnqueueResult(city_tags=[city_tag])
        return EnqueueResult(city_tags=city_tags)

    message = "Failed to enqueue AD."
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
