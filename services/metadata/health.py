"""Deep and public health checks for FM21 metadata service (U31)."""

from __future__ import annotations

import os
from typing import Any

import httpx
import redis
from sqlalchemy import text

from services.db.session import async_session_factory, reset_engine

ComponentResult = dict[str, str]


def _icecast_base_url() -> str:
    host = os.environ.get("ICECAST_HOST", "icecast")
    port = os.environ.get("ICECAST_PORT", "8000")
    return f"http://{host}:{port}"


def _icecast_status_url() -> str:
    override = os.environ.get("ICECAST_HEALTH_URL")
    if override:
        return override
    return f"{_icecast_base_url()}/status-json.xsl"


def _liquidsoap_probe_url() -> str:
    override = os.environ.get("LIQUIDSOAP_HEALTH_URL")
    if override:
        return override
    mount = os.environ.get("LIQUIDSOAP_PROBE_MOUNT", "/moscow")
    return f"{_icecast_base_url()}{mount}"


def check_redis(client: redis.Redis) -> ComponentResult:
    try:
        if not client.ping():
            return {"status": "down", "detail": "ping returned false"}
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 — health probe must not raise
        return {"status": "down", "detail": str(exc)}


async def check_postgres() -> ComponentResult:
    if not os.environ.get("DATABASE_URL"):
        return {"status": "down", "detail": "DATABASE_URL is not set"}
    try:
        reset_engine()
        async with async_session_factory()() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "down", "detail": str(exc)}
    finally:
        reset_engine()


def probe_http(url: str, *, timeout_sec: float = 3.0) -> ComponentResult:
    try:
        response = httpx.get(url, timeout=timeout_sec, follow_redirects=True)
        if response.status_code < 400:
            return {"status": "ok"}
        return {"status": "down", "detail": f"HTTP {response.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "down", "detail": str(exc)}


def public_status(redis_client: redis.Redis) -> tuple[dict[str, str], int]:
    redis_result = check_redis(redis_client)
    if redis_result["status"] == "ok":
        return {"status": "ok"}, 200
    return {"status": "degraded"}, 200


async def deep_status(redis_client: redis.Redis) -> tuple[dict[str, Any], int]:
    components = {
        "redis": check_redis(redis_client),
        "postgres": await check_postgres(),
        "icecast": probe_http(_icecast_status_url()),
        "liquidsoap": probe_http(_liquidsoap_probe_url()),
    }
    if all(component["status"] == "ok" for component in components.values()):
        return {"status": "ok", "components": components}, 200
    return {"status": "degraded", "components": components}, 503
