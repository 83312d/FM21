# Broadcast Semantics Contract

**Authority:** Implement Liquidsoap queue behavior, injector validation, and news scheduler against this document. Supersedes `docs/tz.md` §4 (queue) and §2.3 (data flow) for implementation.

**Requirements:** R2, R3, R5, R6, R7, R8, R9, R10  
**ADR:** [ADR-001](../adr/001-delivery-model.md)

> **R5 mapping:** Requirements R5 lists news stinger and news as separate priority steps. This contract implements them as a single `NEWS_PAIR` enqueue unit at priority 80 (ADR-001 §9).

---

## 1. Scope

This contract defines:

- Per-city broadcast isolation
- Queue item types, priorities, and block boundaries
- Enqueue rules (no interrupt, fan-out, limits)
- Redis keys and JSON item shape
- Internal enqueue API surface

Out of scope: listener UI (see [Listener Contract](listener-contract.md)), Telegram flows (see [Operator Contract](operator-contract.md)), music catalog licensing (see [ADR-002](../adr/002-music-licensing.md)).

---

## 2. City isolation

| Rule | Behavior |
|------|----------|
| **One queue per city** | Redis list `fm21:queue:{cityTag}` per active city |
| **One mount per city** | Icecast mount `/{cityTag}` serves that city's Liquidsoap output |
| **No cross-leak** | An item enqueued for `moscow` is never audible on `spb` (AE1) |
| **Active cities** | Listed in `broadcast/liquidsoap/cities.yaml` (human-maintained) |

Phase 1 active cities: `moscow`, `spb`.

---

## 3. Block model

A **block** is one atomic playback unit on the air:

| Block source | Contents | Interruptible? |
|--------------|----------|----------------|
| `AD` | Single voice ad MP3 | No — plays to end |
| `MUSIC` | Single music track | No |
| `MUSIC_ORDER` | Single ordered track | No |
| `NEWS_PAIR` | Stinger (3–5 s) + news (1–2 min) back-to-back | No — pair is atomic (FG6) |

**No-interrupt rule (R6, AE2, FG4):** While any block plays, dequeue of pending items is suspended. New items enter the pending queue only. After the block ends, Liquidsoap selects the next item by priority rules (§4).

Crossfade between blocks: 2 seconds (configurable in Liquidsoap; default 2s).

---

## 4. Priority and dequeue order

When the current block ends, select the next item:

```
1. Highest priority pending item (see table)
2. Within same priority: FIFO by enqueue timestamp
3. If no pending items: play MUSIC filler from static bed / playlist buffer
4. If filler unavailable: play configured silence or loop fallback — dead air MUST NOT exceed 5s
```

### Priority table

| type | priority | Phase | Description |
|------|----------|-------|-------------|
| `AD` | 100 | 1+ | Geo-targeted voice ad |
| `NEWS_PAIR` | 80 | 2+ | Atomic stinger + news |
| `MUSIC_ORDER` | 50 | 2+ | Bot-ordered track |
| `MUSIC` | 10 | 1+ | Playlist / static bed filler |

Legacy granular types (`NEWS_STINGER`, `NEWS` as separate enqueue units) are **not** used — always `NEWS_PAIR` (ADR-001 §9).

**Dequeue algorithm:** When multiple types share `fm21:queue:{cityTag}`, the consumer must select the highest-priority pending item (then FIFO within priority). Blind tail-only `RPOP`/`BRPOP` does **not** satisfy this rule once Phase 2+ mixes types in the same list. U4 documents the chosen scan-or-structure approach (ADR-001 Appendix A).

### News scheduling (Phase 2+, R7, FG5)

- Cron fires every 15 minutes per city.
- Scheduler enqueues one `NEWS_PAIR` at priority 80.
- If AD items are pending ahead in the queue, news plays after them — scheduler does not preempt current block or skip ahead of pending ads.
- **Maximum slip:** a scheduled news slot must air within **10 minutes** of its target time. If backlog would exceed this, skip the slot and log; do not queue indefinitely behind replenished ads.
- News item play count ≤ 3 per 24 hours (R8); repeat uses cached audio, no re-TTS.

---

## 5. `city_tag = all` fan-out (FG1)

When `city_tag` is `"all"`:

1. Injector validates the item once.
2. **Pre-check:** if any active city's AD queue is at capacity (§6), reject the entire request with HTTP 409 — all-or-nothing, no partial fan-out.
3. For each active city in `cities.yaml`, LPUSH an independent copy to `fm21:queue:{cityTag}` with the same `uri` and `meta`, a **unique `id`**, and `city_tag` set to the **target city** (not `"all"`).
4. Each mount plays the ad on its own timeline after its current block. Content parity across cities is guaranteed; wall-clock simultaneity is **not** — mounts have independent queues and clocks (ADR-001 §7).

Operators set global mode via `/city all` (Operator Contract).

---

## 6. Enqueue limits

| Constraint | Value | On violation |
|------------|-------|--------------|
| AD max duration | 60 seconds | Reject at ingest (bot) — do not enqueue |
| AD max pending per city | 5 (scan `fm21:queue:{cityTag}` items; count those with `type: AD` only — `LLEN` alone is insufficient once mixed types share the list) | HTTP 409 with error payload (R9 sixth-ad case) |
| Invalid `city_tag` | Must be active city or `all` | HTTP 400 |
| Unknown `type` | Must be in §4 table for current phase | HTTP 400 |

Phase 1 injector accepts only `AD`. Static `MUSIC` filler is **Liquidsoap-local** (`data/music/static/`) when Redis is empty — not Redis-enqueued in Phase 1.

**Atomicity:** AD pending-count check and `LPUSH` must run in a single Redis transaction (Lua script or `WATCH`/`MULTI`) so concurrent enqueues cannot exceed five pending ADs per city.

---

## 7. Redis data model

### Keys

```text
fm21:queue:{cityTag}     List  — pending JSON items (LPUSH head, RPOP tail in Phase 1; see §9)
fm21:current:{cityTag}   Hash  — now playing: type, title, artist, started_at, duration_sec
```

Phase 2+ keys (informational): `fm21:news:played:{hash}`, `fm21:playlist:buffer:{cityTag}`.

### Queue item JSON

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "AD",
  "priority": 100,
  "uri": "file:///data/ads/abc123.mp3",
  "city_tag": "moscow",
  "meta": {
    "title": "Voice ad",
    "artist": "",
    "duration_sec": 42
  }
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `id` | yes | UUID; unique per enqueued copy |
| `type` | yes | `AD`, `NEWS_PAIR`, `MUSIC_ORDER`, `MUSIC` |
| `priority` | yes | Must match type per §4 table |
| `uri` | yes | `file://` or `http(s)://` resolvable inside Liquidsoap container |
| `city_tag` | yes | Target city or `all` (fan-out before Redis write) |
| `meta` | yes | At minimum `title`, `duration_sec`; `artist` for music types |

---

## 8. Internal enqueue API

**Endpoint:** `POST /internal/enqueue`  
**Access:** Internal Docker network only — not exposed on public gateway. Callers must send `X-FM21-Internal-Token` matching the `INTERNAL_ENQUEUE_TOKEN` env; gateway denies `/internal/*` on public listeners.

### Request

```json
{
  "type": "AD",
  "uri": "file:///data/ads/abc123.mp3",
  "city_tag": "moscow",
  "meta": {
    "title": "Voice ad",
    "artist": "",
    "duration_sec": 42
  }
}
```

Server assigns `id`, derives `priority` from `type`, validates limits (§6), applies fan-out (§5), LPUSH to Redis.

### Responses

| Code | Meaning |
|------|---------|
| 201 | Enqueued (body includes `id`, `city_tags` affected) |
| 400 | Validation failure (unknown type, bad city, duration) |
| 409 | AD queue full for city (6th pending ad) |

### Callers

- Telegram bot (voice ads) — Phase 1
- News cron worker — Phase 2+
- Music buffer worker — Phase 2+

---

## 9. Liquidsoap implementation guide

An implementer can build `broadcast/liquidsoap/fm21.liq` from this contract alone:

1. **Read `cities.yaml`** — spawn one output pipeline per city.
2. **Per city:** maintain `request.dynamic` or equivalent queue source reading `fm21:queue:{cityTag}`.
3. **On dequeue:** play `uri` to end; apply 2s crossfade to next block.
4. **Filler:** when Redis empty, rotate `data/music/static/*.mp3` (Phase 1).
5. **Metadata:** on block start, HSET `fm21:current:{cityTag}` for metadata service to expose.
6. **NEWS_PAIR (Phase 2):** play `meta.stinger_uri` then `uri` without dequeuing other types between them — or single composite URI; prefer two URIs in `meta` if needed:

```json
{
  "type": "NEWS_PAIR",
  "priority": 80,
  "uri": "file:///data/news/xyz.mp3",
  "city_tag": "moscow",
  "meta": {
    "title": "IT news headline",
    "duration_sec": 90,
    "stinger_uri": "file:///data/news/news-stinger.mp3"
  }
}
```

### Consumption mechanism (U4)

**Chosen path (ADR-001 Appendix A):** Redis poll via `request.dynamic.list` in `broadcast/liquidsoap/fm21.liq` — not harbor push.

| Parameter | Phase 1 value | Notes |
|-----------|---------------|-------|
| Source operator | `request.dynamic.list` per city | Callback runs at each block boundary |
| Dequeue command | `RPOP fm21:queue:{cityTag}` | Invoked via `redis-cli` in container; LPUSH head + RPOP tail = FIFO |
| Poll / retry delay | 1.0 s (`poll_retry_sec`) | Upper bound for re-poll after failure; empty queue still returns bed on same callback |
| Filler | Rotate `data/music/static/bed-*.mp3` | When RPOP returns nothing; no Redis enqueue for Phase 1 bed |
| Crossfade | 2 s | Between all blocks |
| Dead-air cap | < 5 s (§4) | Empty Redis → bed URI returned immediately; `mksafe` guards decoder gaps |
| Now playing | `HMSET fm21:current:{cityTag}` | On block start: `type`, `title`, `artist`, `started_at`, `duration_sec` |

**Phase 1 dequeue note:** Only `AD` items are enqueued to Redis. Blind tail `RPOP` satisfies FIFO and priority (single type). Phase 2+ mixed types require priority scan (`LRANGE` + selective `LREM`) per §4 — replace `dequeue_queue_item` in `fm21.liq`.

**Invariants:**

- Exactly one consumer path per city — no concurrent poll and harbor on the same queue.
- Current block plays to end before the next dequeue (no-interrupt, §3).
- Harbor push remains a deferred alternative; do not run sidecar push alongside poll.

**Reference implementation:** `broadcast/liquidsoap/fm21.liq`, `broadcast/liquidsoap/cities.yaml`, `broadcast/icecast/icecast.xml`.

---

## 10. Acceptance mapping

Machine-verifiable entries: [spec/acceptance.yaml](../../spec/acceptance.yaml).

| Example | Spec ID | Contract sections |
|---------|---------|-------------------|
| AE1 — Moscow ad not on SPB | [AE1](../../spec/acceptance.yaml) | §2, §5 |
| AE2 — Ad waits for news block | [AE2](../../spec/acceptance.yaml) | §3, §4 |
| AE3 — News play count / cache | [AE3](../../spec/acceptance.yaml) | §4 (news scheduling) |
| Sixth ad rejected | [AE-QUEUE-FULL](../../spec/acceptance.yaml) | §6 |
| `all` fan-out | [AE-ALL-FANOUT](../../spec/acceptance.yaml) | §5 |

---

## Appendix — Flow gaps FG1–FG7 (contract coverage)

Flow-gap IDs use the `FG` prefix to avoid collision with requirements Outstanding Questions (Q1, Q2, …).

| ID | Gap | Section |
|----|-----|---------|
| FG1 | `all` fan-out | §5 |
| FG2 | City badge UX | [Listener Contract](listener-contract.md) §3 |
| FG3 | Late joiner / sync radio | [Listener Contract](listener-contract.md) §5 |
| FG4 | No-interrupt | §3 |
| FG5 | News behind ad backlog | §4 |
| FG6 | Stinger+news atomic | §3, §9 |
| FG7 | City switch reconnect | [Listener Contract](listener-contract.md) §4 |
