"""Now-playing reader for fm21:current:{cityTag} (Listener Contract §6, U7/U28)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import redis
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.geo.cities import CityRegistry

ContentType = Literal["music", "news", "ad"]

_TYPE_MAP: dict[str, ContentType] = {
    "MUSIC": "music",
    "MUSIC_ORDER": "music",
    "NEWS_PAIR": "news",
    "AD": "ad",
}

CURRENT_KEY_PREFIX = "fm21:current:"


class NowPlayingResponse(BaseModel):
    city_tag: str
    title: str
    artist: str | None = None
    content_type: ContentType
    started_at: str
    duration_sec: int
    remaining_sec: int


def utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_epoch_seconds(stripped: str) -> float | None:
    if stripped.isdigit():
        return float(stripped)
    try:
        return float(stripped)
    except ValueError:
        return None


def _parse_started_at(raw: str | None) -> str:
    if not raw:
        return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")
    stripped = raw.strip()
    epoch = _parse_epoch_seconds(stripped)
    if epoch is not None:
        started = datetime.fromtimestamp(epoch, tz=UTC)
        if stripped.isdigit():
            started = started.replace(microsecond=0)
        return started.isoformat().replace("+00:00", "Z")
    if stripped.endswith("Z"):
        return stripped
    try:
        parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_started_at_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    stripped = raw.strip()
    epoch = _parse_epoch_seconds(stripped)
    if epoch is not None:
        return datetime.fromtimestamp(epoch, tz=UTC)
    try:
        parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return None


def _map_content_type(raw: str | None) -> ContentType:
    if not raw:
        return "music"
    return _TYPE_MAP.get(raw.upper(), "music")


def compute_remaining_sec(
    *,
    started_at_raw: str | None,
    duration_sec: int,
    now: datetime | None = None,
) -> int:
    started = _parse_started_at_dt(started_at_raw)
    if started is None:
        return duration_sec
    current = (now or utc_now()).astimezone(UTC)
    elapsed = (current - started).total_seconds()
    return max(0, int(duration_sec - elapsed))


def read_now_playing(
    client: redis.Redis,
    registry: CityRegistry,
    city_tag: str,
    *,
    now: datetime | None = None,
) -> NowPlayingResponse | JSONResponse:
    if registry.get(city_tag) is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "unknown_city",
                "message": "cityTag is not an active broadcast city",
            },
        )

    key = f"{CURRENT_KEY_PREFIX}{city_tag}"
    data = client.hgetall(key)
    if not data:
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_playing",
                "message": f"no current block for {city_tag}",
            },
        )

    title = data.get("title") or "FM21"
    artist = data.get("artist") or None
    if artist == "":
        artist = None
    duration_raw = data.get("duration_sec", "240")
    try:
        duration_sec = max(1, int(duration_raw))
    except (TypeError, ValueError):
        duration_sec = 240

    started_at_raw = data.get("started_at")
    return NowPlayingResponse(
        city_tag=city_tag,
        title=title,
        artist=artist,
        content_type=_map_content_type(data.get("type")),
        started_at=_parse_started_at(started_at_raw),
        duration_sec=duration_sec,
        remaining_sec=compute_remaining_sec(
            started_at_raw=started_at_raw,
            duration_sec=duration_sec,
            now=now,
        ),
    )
