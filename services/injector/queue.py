"""Redis queue operations with atomic AD capacity checks (Broadcast Semantics §6)."""

from __future__ import annotations

import json
from typing import Any

import redis

QUEUE_KEY_PREFIX = "fm21:queue:"
PLAYLIST_BUFFER_KEY_PREFIX = "fm21:playlist:buffer:"
PLAYLIST_FINGERPRINT_KEY_PREFIX = "fm21:playlist:fingerprint:"

# Atomic: count pending AD items (not LLEN), reject if at capacity, else LPUSH.
# Returns [1, new_count] on success, [0, 'QUEUE_FULL'] on capacity violation.
_ENQUEUE_AD_LUA = """
local max_ads = tonumber(ARGV[1])
local payload = ARGV[2]
local items = redis.call('LRANGE', KEYS[1], 0, -1)
local ad_count = 0
for _, item in ipairs(items) do
    local ok, decoded = pcall(cjson.decode, item)
    if ok and decoded.type == 'AD' then
        ad_count = ad_count + 1
    end
end
if ad_count >= max_ads then
    return {0, 'QUEUE_FULL'}
end
redis.call('LPUSH', KEYS[1], payload)
return {1, ad_count + 1}
"""

# Atomic fan-out: pre-check all keys, LPUSH all or reject with no writes.
# KEYS = one queue key per city; ARGV[1] = max_ads; ARGV[2..] = JSON payloads per key.
_FANOUT_AD_LUA = """
local max_ads = tonumber(ARGV[1])
local num_keys = #KEYS
for i = 1, num_keys do
    local items = redis.call('LRANGE', KEYS[i], 0, -1)
    local ad_count = 0
    for _, item in ipairs(items) do
        local ok, decoded = pcall(cjson.decode, item)
        if ok and decoded.type == 'AD' then
            ad_count = ad_count + 1
        end
    end
    if ad_count >= max_ads then
        return {0, 'QUEUE_FULL', KEYS[i]}
    end
end
for i = 1, num_keys do
    redis.call('LPUSH', KEYS[i], ARGV[i + 1])
end
return {1, num_keys}
"""


class QueueFullError(Exception):
    def __init__(self, city_tag: str) -> None:
        self.city_tag = city_tag
        super().__init__(f"AD queue full for {city_tag}")


class QueueClient:
    def __init__(self, redis_url: str, max_pending_ads: int) -> None:
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._max_pending_ads = max_pending_ads
        self._enqueue_ad = self._redis.register_script(_ENQUEUE_AD_LUA)
        self._fanout_ad = self._redis.register_script(_FANOUT_AD_LUA)

    def queue_key(self, city_tag: str) -> str:
        return f"{QUEUE_KEY_PREFIX}{city_tag}"

    def count_pending_ads(self, city_tag: str) -> int:
        items = self._redis.lrange(self.queue_key(city_tag), 0, -1)
        return sum(1 for raw in items if _item_type(raw) == "AD")

    def count_pending_music(self, city_tag: str) -> int:
        items = self._redis.lrange(self.queue_key(city_tag), 0, -1)
        return sum(1 for raw in items if _item_type(raw) == "MUSIC")

    def playlist_buffer_key(self, city_tag: str) -> str:
        return f"{PLAYLIST_BUFFER_KEY_PREFIX}{city_tag}"

    def list_playlist_buffer(self, city_tag: str) -> list[str]:
        return self._redis.lrange(self.playlist_buffer_key(city_tag), 0, -1)

    def record_playlist_buffer(self, city_tag: str, track_id: str, *, max_len: int = 100) -> None:
        key = self.playlist_buffer_key(city_tag)
        pipe = self._redis.pipeline()
        pipe.lpush(key, track_id)
        pipe.ltrim(key, 0, max_len - 1)
        pipe.execute()

    def enqueue_item(self, city_tag: str, item: dict[str, Any]) -> None:
        payload = json.dumps(item, separators=(",", ":"))
        self._redis.lpush(self.queue_key(city_tag), payload)

    def enqueue_ad(self, city_tag: str, item: dict[str, Any]) -> None:
        payload = json.dumps(item, separators=(",", ":"))
        result = self._enqueue_ad(keys=[self.queue_key(city_tag)], args=[self._max_pending_ads, payload])
        if int(result[0]) == 0:
            raise QueueFullError(city_tag)

    def fanout_ad(self, city_items: list[tuple[str, dict[str, Any]]]) -> None:
        if not city_items:
            return
        keys = [self.queue_key(city) for city, _ in city_items]
        payloads = [json.dumps(item, separators=(",", ":")) for _, item in city_items]
        result = self._fanout_ad(keys=keys, args=[self._max_pending_ads, *payloads])
        if int(result[0]) == 0:
            full_key = result[2]
            city_tag = full_key.removeprefix(QUEUE_KEY_PREFIX)
            raise QueueFullError(city_tag)

    def list_items(self, city_tag: str) -> list[dict[str, Any]]:
        raw_items = self._redis.lrange(self.queue_key(city_tag), 0, -1)
        return [json.loads(raw) for raw in raw_items]

    def playlist_fingerprint_key(self, city_tag: str) -> str:
        return f"{PLAYLIST_FINGERPRINT_KEY_PREFIX}{city_tag}"

    def get_playlist_fingerprint(self, city_tag: str) -> str | None:
        value = self._redis.get(self.playlist_fingerprint_key(city_tag))
        return value if value else None

    def set_playlist_fingerprint(self, city_tag: str, fingerprint: str) -> None:
        self._redis.set(self.playlist_fingerprint_key(city_tag), fingerprint)

    def clear_playlist_buffer(self, city_tag: str) -> None:
        self._redis.delete(self.playlist_buffer_key(city_tag))

    def remove_pending_items_by_type(self, city_tag: str, item_type: str) -> int:
        """Drop queued items of one type; preserve relative order of the rest."""
        key = self.queue_key(city_tag)
        raw_items = self._redis.lrange(key, 0, -1)
        kept: list[str] = []
        removed = 0
        for raw in raw_items:
            if _item_type(raw) == item_type:
                removed += 1
            else:
                kept.append(raw)
        if removed:
            pipe = self._redis.pipeline()
            pipe.delete(key)
            if kept:
                for raw in reversed(kept):
                    pipe.lpush(key, raw)
            pipe.execute()
        return removed

    def flush_all(self, city_tags: list[str]) -> None:
        pipe = self._redis.pipeline()
        for city in city_tags:
            pipe.delete(self.queue_key(city))
            pipe.delete(self.playlist_buffer_key(city))
            pipe.delete(self.playlist_fingerprint_key(city))
        pipe.execute()


def _item_type(raw: str) -> str | None:
    try:
        return json.loads(raw).get("type")
    except (json.JSONDecodeError, AttributeError):
        return None
