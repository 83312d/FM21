---
module: music
date: 2026-06-09
problem_type: architecture_pattern
component: services/music, broadcast/liquidsoap
symptoms:
  - "Buffer worker enqueues fewer than 10 MUSIC items with static catalog"
  - "Yandex HTTPS URLs fail HEAD probe or expire while queued"
  - "YandexProvider cache writes fail when DB session closes before resolve"
root_cause: "Enqueue-time dedupe and HTTP HEAD probes conflict with small static catalogs and Yandex signed URL semantics; async session scope ended before stream URL resolution."
resolution_type: pattern
tags: [yandex, liquidsoap, redis, dequeue, buffer-worker, phase-2]
---

# Phase 2: Yandex URL expiry and priority dequeue patterns

## Problem

Phase 2 introduced `MusicProvider`, a Redis MUSIC buffer (≥10 per city), Lua priority dequeue, and bot `/order`. Several integration edges only appear with a live stack, not unit tests alone.

## Patterns

### 1. Yandex signed URLs vs enqueue-time resolve

Stream URLs expire (often within minutes). Resolving at buffer-fill or `/order` confirm and storing `https://` in Redis is acceptable for **short queue depth** and **fast consumption**, but URLs can die if AD blocks delay playback.

**Mitigations applied in U10–U14:**

- `tracks_cache` with re-resolve when expiry is within 2 minutes (`STREAM_URL_REFRESH_BUFFER`).
- Unknown CDN expiry → assume short TTL (2 min), not 1 hour.
- Liquidsoap: **do not HEAD-probe** Yandex URLs (many CDNs return 403 on HEAD); play directly and fall back to bed on decoder failure.
- `SafeYandexClient` wrapper: never expose OAuth token in `repr` / exception chains (`raise ... from None` on auth errors).

**Future (Phase 3+):** resolve at dequeue via internal pre-play endpoint or store `track_id` + resolve in Liquidsoap hook.

### 2. Priority dequeue (Lua + Liquidsoap)

`broadcast/liquidsoap/dequeue.lua` implements contract §4:

- `LRANGE` full list → pick max `priority` → FIFO within tier (oldest at tail) → `LREM` one matching JSON.
- `NEWS_PAIR`: two pipe-delimited lines (`stinger` then `main`) from one atomic dequeue.
- `dequeue.sh` must **not** swallow Redis errors (`2>/dev/null || true` hides pending queue).

Liquidsoap reads lines via `process.read.lines`; empty result → static bed (dead air <5s).

### 3. Buffer worker steady state (≥10 MUSIC)

Target is **pending MUSIC count**, not unique catalog size.

- Small static catalog (5 MP3s) must **cycle** tracks to reach 10 — do not exclude track IDs already in queue.
- `fm21:playlist:buffer:{city}` dedupe applies to **MUSIC_ORDER** recent plays only (injector records buffer on `MUSIC_ORDER`, not filler `MUSIC`).
- `create_music_provider(session)` session must stay open through `resolve_stream_url` (cache upsert uses same `AsyncSession`).

### 4. Compose wiring

`music-worker` and `bot` need `YANDEX_MUSIC_OAUTH_TOKEN` from `.env`. Rebuild `injector` / `music-worker` images after Phase 2 code lands — stale images return 422 on `MUSIC` enqueue.

Placeholder playlist IDs in `playlist_rules.yaml` (`1030:5`) fail Yandex fetch → static fallback until replaced with real `uid:kind` from the operator account.

## Verification

```bash
docker compose run --rm test pytest tests/ -q
# Stop liquidsoap to observe buffer without consumption:
docker compose stop liquidsoap
docker compose exec redis redis-cli FLUSHDB
docker compose up -d music-worker
# Expect LLEN fm21:queue:moscow >= 10
docker compose exec redis redis-cli LLEN fm21:queue:moscow
```

## Related

- [ADR-002](../../adr/002-music-licensing.md)
- [Broadcast semantics §4](../../contracts/broadcast-semantics.md)
- Plan U9–U14 in `docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md`
