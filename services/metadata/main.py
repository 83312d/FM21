"""FM21 metadata API — GET /api/now-playing/{cityTag} from Redis."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

import redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.geo.cities import CityRegistry, load_registry

logger = logging.getLogger(__name__)

ContentType = Literal["music", "news", "ad"]

_TYPE_MAP: dict[str, ContentType] = {
    "MUSIC": "music",
    "MUSIC_ORDER": "music",
    "NEWS_PAIR": "news",
    "AD": "ad",
}


class NowPlayingResponse(BaseModel):
    city_tag: str
    title: str
    artist: str | None = None
    content_type: ContentType
    started_at: str
    duration_sec: int


class ErrorResponse(BaseModel):
    error: str
    message: str | None = None


def _redis_client() -> redis.Redis:
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return redis.Redis.from_url(url, decode_responses=True)


def _parse_started_at(raw: str | None) -> str:
    if not raw:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    stripped = raw.strip()
    if stripped.isdigit():
        ts = int(stripped)
        return datetime.fromtimestamp(ts, tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if stripped.endswith("Z"):
        return stripped
    try:
        parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _map_content_type(raw: str | None) -> ContentType:
    if not raw:
        return "music"
    return _TYPE_MAP.get(raw.upper(), "music")


def _read_now_playing(
    client: redis.Redis,
    registry: CityRegistry,
    city_tag: str,
) -> NowPlayingResponse | JSONResponse:
    if registry.get(city_tag) is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "unknown_city",
                "message": "cityTag is not an active broadcast city",
            },
        )

    key = f"fm21:current:{city_tag}"
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

    return NowPlayingResponse(
        city_tag=city_tag,
        title=title,
        artist=artist,
        content_type=_map_content_type(data.get("type")),
        started_at=_parse_started_at(data.get("started_at")),
        duration_sec=duration_sec,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = load_registry()
    client = _redis_client()
    app.state.registry = registry
    app.state.redis = client
    yield
    client.close()


app = FastAPI(title="FM21 Metadata API", version="0.1.0", lifespan=lifespan)


@app.get("/api/now-playing/{city_tag}")
def now_playing(city_tag: str):
    registry: CityRegistry = app.state.registry
    client: redis.Redis = app.state.redis
    result = _read_now_playing(client, registry, city_tag)
    if isinstance(result, JSONResponse):
        return result
    logger.info(
        "now-playing city_tag=%s content_type=%s title=%s",
        result.city_tag,
        result.content_type,
        result.title,
    )
    return result
