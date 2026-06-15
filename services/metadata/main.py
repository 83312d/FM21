"""FM21 metadata API — now-playing and queue preview from Redis."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from services.common.logging import configure_json_logging
from services.geo.cities import CityRegistry, load_registry
from services.metadata.health import deep_status, public_status
from services.metadata.now_playing import read_now_playing
from services.metadata.queue_reader import read_queue_preview

configure_json_logging(service="metadata")
logger = logging.getLogger(__name__)


def _redis_client() -> redis.Redis:
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return redis.Redis.from_url(url, decode_responses=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry = load_registry()
    client = _redis_client()
    app.state.registry = registry
    app.state.redis = client
    yield
    client.close()


app = FastAPI(title="FM21 Metadata API", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
def api_health():
    """Public liveness — status only (ok/degraded); no dependency topology."""
    body, status_code = public_status(app.state.redis)
    return JSONResponse(content=body, status_code=status_code)


@app.get("/internal/health")
async def internal_health():
    """Deep health for operators — not exposed on the public gateway."""
    body, status_code = await deep_status(app.state.redis)
    return JSONResponse(content=body, status_code=status_code)


@app.get("/api/now-playing/{city_tag}")
def now_playing(city_tag: str):
    registry: CityRegistry = app.state.registry
    client: redis.Redis = app.state.redis
    result = read_now_playing(client, registry, city_tag)
    if isinstance(result, JSONResponse):
        return result
    logger.info(
        "now-playing city_tag=%s content_type=%s title=%s remaining_sec=%s",
        result.city_tag,
        result.content_type,
        result.title,
        result.remaining_sec,
    )
    return result


@app.get("/api/queue/{city_tag}")
def queue_preview(city_tag: str):
    registry: CityRegistry = app.state.registry
    client: redis.Redis = app.state.redis
    result = read_queue_preview(client, registry, city_tag)
    if isinstance(result, JSONResponse):
        return result
    logger.info("queue-preview city_tag=%s items=%s", result.city_tag, len(result.items))
    return result
