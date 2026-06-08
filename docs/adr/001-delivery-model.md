# ADR-001: Delivery model — synchronous multi-mount broadcast

**Status:** Accepted  
**Date:** 2026-06-08  
**Deciders:** Product owner  
**Requirements:** R2, R5, R6, R32

## Context

FM21 is geotargeted internet radio: listeners sharing a `city_tag` must hear the same content at the same time (synchronous radio), while ads and orders target specific cities. The legacy brief (`docs/tz.md`) mixes sync semantics with client-side Web Audio stitching and HLS/WebSocket delivery — approaches that imply per-listener timelines.

We need a delivery model that:

- Isolates broadcast queues and streams per `city_tag` (R2).
- Supports global content via `city_tag = all` (R3).
- Never interrupts the currently playing block (R6).
- Runs entirely inside Docker containers (ADR-003).

## Decision

### 1. Synchronous radio per `city_tag`

All listeners on a city mount share one server-side timeline. A listener who joins late hears whatever is **currently airing** on that mount — they do not receive a personal replay of content that already played (see AE5). Ordered music and ads enter the city's shared queue and air in queue order for everyone connected to that mount.

### 2. Liquidsoap + Icecast as broadcast spine

- **Liquidsoap** owns queue dequeue, crossfade, and stream generation per city.
- **Icecast** exposes one ICY mount per active `city_tag` (e.g. `http://icecast:8000/moscow`, `http://icecast:8000/spb`).
- Glue services (bot, injector, music, news) do **not** mux audio on the client; they enqueue URIs for Liquidsoap to play.

Rejected alternatives (see ideation #1, #7):

- Personalized HLS manifests per listener — async timeline, incompatible with sync radio.
- Client-side Web Audio segment stitching — async timeline, high implementation risk.

### 3. ICY as primary listener protocol (Phase 1)

Listeners use standard `<audio src="…/{cityTag}">` against the Icecast mount. Target latency: 2–5 seconds. Metadata (now playing, content type) arrives on a **separate HTTP poll channel** — not embedded in a WebSocket audio stream (KTD-3). Audio playback continues if the metadata API is temporarily unavailable.

HLS adaptive streaming is deferred; it adds segment latency incompatible with tight sync-radio UX unless tuned specifically.

### 4. Redis list as enqueue bus

Services push JSON queue items to Redis lists:

```text
fm21:queue:{cityTag}   — List, LPUSH by injector, consumed by Liquidsoap
fm21:current:{cityTag} — Hash, now-playing metadata (written by broadcast/metadata)
```

Item shape (canonical):

```json
{
  "id": "uuid",
  "type": "AD | NEWS_PAIR | MUSIC_ORDER | MUSIC",
  "priority": 100 | 80 | 50 | 10,
  "uri": "file:///data/ads/xxx.mp3",
  "city_tag": "moscow | spb | all",
  "meta": { "title": "...", "artist": "...", "duration_sec": 45 }
}
```

`NEWS_PAIR` (Phase 2+) is a single enqueue unit containing stinger + news — see §6.

Liquidsoap consumes the queue via `request.dynamic` or a sidecar poller pushing harbor requests. The exact mechanism is resolved in U4 and documented in the Broadcast Semantics contract appendix; the invariant is **Redis is the source of truth for pending items**.

### 5. No mid-block interruption

A **block** is one contiguous playback unit: a single AD, MUSIC track, MUSIC_ORDER track, or atomic NEWS_PAIR (stinger + news as one block in Phase 2+). While a block plays, newly enqueued items wait in the priority queue. They dequeue only after the current block ends (R6, AE2).

### 6. Priority order

| Priority | Type | Phase |
|----------|------|-------|
| 100 | `AD` — voice ad | 1 |
| 80 | `NEWS_PAIR` — stinger + news (atomic) | 2+ |
| 50 | `MUSIC_ORDER` — bot-ordered track | 2 |
| 10 | `MUSIC` — playlist filler | 1 (static bed), 2 (Yandex) |

Within the same priority, FIFO by enqueue time.

### 7. `city_tag = all` fan-out (flow gap FG1)

When an operator or service enqueues with `city_tag: "all"`, the injector **duplicates** the item into every active city's Redis list (`fm21:queue:moscow`, `fm21:queue:spb`, …). Each copy is independent; playback timing may differ slightly per mount due to independent Liquidsoap clocks, but all cities receive the same content. Phase 1 active cities are defined in `broadcast/liquidsoap/cities.yaml` (human-maintained).

### 8. News waits behind ad backlog (flow gap FG5)

When a 15-minute news slot fires (Phase 2+), the scheduler enqueues a `NEWS_PAIR` at priority 80. If AD items are still pending in the queue, news plays **after** all higher-priority pending items that were already queued — it does not preempt the current block or jump ahead of pending ads. **Maximum slip:** if backlog would delay news more than 10 minutes past the scheduled slot, skip the slot and log. **No interrupt** is invariant.

### 9. Stinger + news as atomic pair (flow gap FG6)

News airs as one logical block: 3–5 second «Сейчас новости» stinger immediately followed by the 1–2 minute news segment. Nothing inserts between stinger and news. Enqueue as a single `NEWS_PAIR` type; Liquidsoap plays both URIs back-to-back without dequeuing other types in between.

### 10. Phase 1 scope

Phase 1 proves geo isolation with:

- Two mounts: `moscow`, `spb`.
- Static `MUSIC` bed from disk (`data/music/static/`).
- `AD` type only from Telegram voice pipeline.
- No news, no `MUSIC_ORDER`, no Yandex.

## Consequences

### Positive

- One Liquidsoap script parameterized by `cities.yaml` scales to N cities.
- Standard streaming playback — no custom browser audio graph.
- Contracts (Broadcast Semantics, Listener, Operator) survive stack changes.
- Agents implement against Redis + mount semantics, not `docs/tz.md` Node/HLS details.

### Negative

- Idle cities still consume broadcast resources (acceptable for Phase 1–2 scale).
- Late joiners miss content already aired — must be communicated in player UX (AE5).
- Liquidsoap DSL learning curve for queue integration.

## Related

- [ADR-002](002-music-licensing.md) — music source for `MUSIC` / `MUSIC_ORDER` items
- [ADR-003](003-container-strategy.md) — broadcast processes run in containers
- [Broadcast Semantics](../contracts/broadcast-semantics.md) — implementer-facing queue rules
- [Listener Contract](../contracts/listener-contract.md) — sync radio UX (late joiner, city switch)
- KTD-1, KTD-2, KTD-4, KTD-8 in implementation plan

## Appendix A — Liquidsoap consumption mechanism

**Status:** Deferred to U4 spike.

Candidates:

1. **Redis poll** — Liquidsoap external script or `request.dynamic` polls `fm21:queue:{cityTag}`.
2. **Harbor push** — Injector sidecar pushes `request.create` to Liquidsoap harbor on LPUSH.

Selection criteria: reliability under empty queue, crossfade compatibility, ops simplicity in Docker Compose. Document the chosen path in Broadcast Semantics when U4 lands.

## Appendix B — Flow gaps resolved by this ADR and contracts

Flow-gap IDs use the `FG` prefix (see Broadcast Semantics appendix) to avoid collision with requirements Outstanding Questions Q1, Q2, …

| Gap | Topic | Resolution |
|-----|-------|------------|
| FG1 | `all` fan-out | §7 — duplicate to every active city list |
| FG2 | City badge UX | Listener Contract — badge + change control, no blocking modal |
| FG3 | Late joiner / sync radio | §1, Listener Contract — live edge only; AE5 |
| FG4 | No-interrupt | §5 — block definition; AE2 |
| FG5 | News vs ad backlog | §8 — news after pending ads; 10 min max slip |
| FG6 | Stinger+news atomicity | §9 — `NEWS_PAIR` single block |
| FG7 | City switch during playback | Listener Contract — immediate reconnect to new mount live edge |
