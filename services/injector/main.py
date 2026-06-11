"""Queue injector — POST /internal/enqueue (Broadcast Semantics §8)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from services.injector.fanout import ENQUEUE_TYPES, load_active_cities, prepare_enqueue
from services.injector.queue import QueueClient, QueueFullError

MAX_PENDING_ADS = int(os.environ.get("MAX_PENDING_ADS_PER_CITY", "5"))
MAX_AD_DURATION_SEC = int(os.environ.get("MAX_AD_DURATION_SEC", "60"))
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CITIES_YAML_PATH = os.environ.get("CITIES_YAML_PATH", "broadcast/liquidsoap/cities.yaml")


class EnqueueMeta(BaseModel):
    title: str
    artist: str = ""
    duration_sec: int = Field(ge=1)
    track_id: str = ""
    stinger_uri: str = ""


class EnqueueRequest(BaseModel):
    type: Literal["AD", "MUSIC", "MUSIC_ORDER", "NEWS_PAIR"]
    uri: str = Field(min_length=1)
    city_tag: str
    meta: EnqueueMeta


class EnqueueResponse(BaseModel):
    id: str
    ids: list[str]
    city_tags: list[str]


class ErrorResponse(BaseModel):
    error: str
    message: str
    city_tag: str | None = None


def _require_internal_token(
    x_fm21_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    internal_token = os.environ.get("INTERNAL_ENQUEUE_TOKEN", "")
    if not internal_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="INTERNAL_ENQUEUE_TOKEN not configured",
        )
    if x_fm21_internal_token != internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal token",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.active_cities = load_active_cities(CITIES_YAML_PATH)
    app.state.queue = QueueClient(REDIS_URL, MAX_PENDING_ADS)
    yield


app = FastAPI(title="FM21 Injector", lifespan=lifespan)


def _validate_request(body: EnqueueRequest, active_cities: list[str]) -> None:
    if body.type not in ENQUEUE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or unsupported type: {body.type}",
        )
    if body.city_tag != "all" and body.city_tag not in active_cities:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid city_tag: {body.city_tag}",
        )
    if body.type == "AD" and body.meta.duration_sec > MAX_AD_DURATION_SEC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"AD duration exceeds {MAX_AD_DURATION_SEC}s limit",
        )


@app.post(
    "/internal/enqueue",
    response_model=EnqueueResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"model": ErrorResponse},
    },
)
def enqueue(
    body: EnqueueRequest,
    _: Annotated[None, Depends(_require_internal_token)],
) -> EnqueueResponse:
    active_cities: list[str] = app.state.active_cities
    queue: QueueClient = app.state.queue

    _validate_request(body, active_cities)

    meta: dict[str, Any] = {
        "title": body.meta.title,
        "artist": body.meta.artist,
        "duration_sec": body.meta.duration_sec,
    }
    if body.meta.track_id:
        meta["track_id"] = body.meta.track_id
    if body.meta.stinger_uri:
        meta["stinger_uri"] = body.meta.stinger_uri
    city_items = prepare_enqueue(
        item_type=body.type,
        uri=body.uri,
        city_tag=body.city_tag,
        meta=meta,
        active_cities=active_cities,
    )
    if not city_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid city_tag: {body.city_tag}",
        )

    try:
        if body.type == "AD":
            if len(city_items) == 1:
                city, item = city_items[0]
                queue.enqueue_ad(city, item)
            else:
                queue.fanout_ad(city_items)
        else:
            for city, item in city_items:
                queue.enqueue_item(city, item)
                track_id = meta.get("track_id")
                if track_id and body.type == "MUSIC_ORDER":
                    queue.record_playlist_buffer(city, track_id)
    except QueueFullError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "queue_full",
                "message": f"AD queue full for {exc.city_tag} (max {MAX_PENDING_ADS} pending)",
                "city_tag": exc.city_tag,
            },
        ) from exc

    ids = [item["id"] for _, item in city_items]
    city_tags = [city for city, _ in city_items]
    return EnqueueResponse(id=ids[0], ids=ids, city_tags=city_tags)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
