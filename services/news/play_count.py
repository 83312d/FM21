"""Redis mirror for news play counts — ADR-007, U19."""

from __future__ import annotations

import os

import redis

PLAYED_KEY_PREFIX = "fm21:news:played:"
PLAYED_TTL_SEC = 86400
MAX_PLAYS_PER_24H = 3


def played_key(content_hash: str) -> str:
    return f"{PLAYED_KEY_PREFIX}{content_hash}"


def redis_client_from_env() -> redis.Redis:
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return redis.Redis.from_url(url, decode_responses=True)


def get_played_count(client: redis.Redis, content_hash: str) -> int:
    raw = client.get(played_key(content_hash))
    if raw is None:
        return 0
    return int(raw)


def is_at_play_cap(
    client: redis.Redis,
    content_hash: str,
    *,
    cap: int = MAX_PLAYS_PER_24H,
) -> bool:
    return get_played_count(client, content_hash) >= cap


def increment_played_count(client: redis.Redis, content_hash: str) -> int:
    """Mirror one air-slot play; TTL set on first increment in the window."""
    key = played_key(content_hash)
    count = client.incr(key)
    if count == 1:
        client.expire(key, PLAYED_TTL_SEC)
    return count


def clear_played_keys(client: redis.Redis) -> int:
    """Delete all fm21:news:played:* keys (midnight reset)."""
    deleted = 0
    for key in client.scan_iter(match=f"{PLAYED_KEY_PREFIX}*"):
        client.delete(key)
        deleted += 1
    return deleted
