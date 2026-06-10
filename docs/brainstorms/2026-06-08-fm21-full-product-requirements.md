---
date: 2026-06-08
topic: fm21-full-product
supersedes_scope: docs/brainstorms/2026-06-08-fm21-requirements.md (geo-slice sequencing only)
origin_brief: docs/tz.md
---

# Requirements: FM21 — Full Product (per TZ v1.1)

## Summary

Deliver the complete FM21 product described in `docs/tz.md` v1.1: geotargeted autonomous internet radio with continuous music (Yandex Music), IT news every 15 minutes (fetch → summarize RU → TTS), voice ads and music orders via Telegram, and a web player with geo detection — all runnable in production behind HTTPS. Stack is **not** bound to Node.js or client-side Web Audio stitching from the legacy brief; delivery uses server-side synchronous radio (Liquidsoap + Icecast), Python glue services, PostgreSQL, Redis, and Docker.

**Success:** A listener opens the site, hears their city's live stream with music and news on schedule; an operator controls the air from Telegram without touching infrastructure; `docs/tz.md` §12 acceptance criteria are verifiable end-to-end.

---

## Problem Frame

The original greenfield plan delivered a **geo vertical slice** (two cities, static music, one ad) as a risk proof. That is not the product in `docs/tz.md`. The TZ describes a shippable autonomous radio: Yandex-filled airtime, 15-minute news blocks, full bot commands, PostgreSQL persistence, cron hygiene, and production deployment.

Technical choices already validated in-repo (ADR-001/002/003, behavior contracts) are **retained** where they satisfy TZ behavior better than the legacy implementation sections (HLS/WebSocket/Web Audio mux). Everything else is specified here for planning and implementation.

---

## Key Decisions

**Full TZ scope, not geo proof only.** All modules in TZ §2–§4, §6–§9, §12 ship. Phase ordering follows TZ §11 intent (foundation → music → playback → news → bot → production) but uses vertical slices per module, not horizontal layers.

**Server-side synchronous radio per `city_tag`.** Liquidsoap + Icecast; one ICY mount per city; shared timeline per mount (ADR-001). Client uses `<audio>` + HTTP metadata poll — not HLS manifest, WebSocket audio, or Web Audio segment stitching (TZ §6.4 / §7.1 delivery sections superseded for implementation).

**`NEWS_PAIR` atomic block.** Stinger + news enqueue as one unit at priority 80 (not separate `NEWS_STINGER` + `NEWS` items from TZ §4.1).

**Python 3.12 glue services.** FastAPI for HTTP APIs; `python-telegram-bot` webhook; ffmpeg subprocess for transcode. Replaces TZ's Node.js service layout.

**PostgreSQL + Redis.** PostgreSQL for durable entities (`news_items`, `ads`, `tracks_cache`, `playlist_config`, `broadcast_log` per TZ §8.1). Redis for live queue and now-playing (`fm21:queue:{cityTag}`, `fm21:current:{cityTag}`, counters per TZ §8.2).

**Yandex Music via personal OAuth — closed beta.** Unofficial API acceptable for friends-only beta (ADR-002). `MusicProvider` abstraction; static/royalty-free fallback on failure.

**News pipeline.** RSS registry (human-maintained `sources.yaml`) + optional search API fallback; GigaChat summarizer → 150–250 word RU; Neurozvuk TTS (`lang=ru`); pre-generation 2 minutes before slot; play_count ≤ 3 / 24h without re-TTS.

**Docker images everywhere; Compose dev-only.** Same images for CI/staging/production (ADR-003). Production manifests in `deploy/`, not root Compose.

**Agent workflow unchanged.** This document does not modify `AGENTS.md`, runbooks, or compound-engineering configuration — human concern.

---

## Actors

- **A1. Listener** — opens web player, no account; hears city stream; overrides city via badge or URL
- **A2. Operator** — Telegram: voice ads, `/order`, `/city`, `/status`
- **A3. Admin** — `/playlist` rule changes; `TELEGRAM_ADMIN_IDS`
- **A4. System** — cron workers (news, playlist refresh, cleanup), music buffer, broadcast dequeue

---

## Requirements

### Product — Geotargeting (TZ §1, §2.2)

- R1. City detection order: `?city=` → `localStorage.fm21_city` → geolocation (5s timeout) → reverse geocode → IP GeoIP → default city.
- R2. Each `city_tag` has isolated queue and ICY stream; city A content never audible on city B.
- R3. `city_tag=all` fans out to every active city (independent queue copies).
- R4. City badge visible; change city reconnects to live mount edge immediately; no blocking modal before Play.

### Product — Broadcast (TZ §4, §1.1)

- R5. Priority: AD (100) → NEWS_PAIR (80) → MUSIC_ORDER (50) → MUSIC (10); FIFO within tier.
- R6. No mid-block interrupt; enqueue waits for current block end.
- R7. News slot every 15 minutes per city; 3–5s stinger «Сейчас новости» + 1–2 min voiced segment (atomic NEWS_PAIR).
- R8. Same news item ≤ 3 plays / 24h; repeats use cached audio, no re-TTS.
- R9. Voice ads: max 60s, max 5 pending AD per city.
- R10. Music fills all time not occupied by ads, news, or orders; buffer ≥ 10 MUSIC items per city.

### Product — Listener UX (TZ §6)

- R11. Open access, no listener auth.
- R12. Mandatory Play/Pause (autoplay policy).
- R13. Volume 0–100%, persisted in localStorage.
- R14. Now-playing: title, artist (if applicable), type label music | news | ad.
- R15. City badge with human-readable name.
- R16. Background tab playback continues (Chrome, Firefox, Safari).
- R17. Colors `#44EB99` accent, `#861BE3` primary, dark background per TZ §6.2.

### Product — News (TZ §3.1)

- R18. IT news from global sources (HN, TechCrunch, Verge, Ars, Habr, etc.) via RSS + optional search.
- R19. Summarize to original Russian 150–250 words (~1–2 min @ 130 wpm).
- R20. TTS via Neurozvuk or equivalent with Russian stress; cache text + MP3.
- R21. Cron `*/15 * * * *` enqueue NEWS_PAIR to all active cities.
- R22. Pre-generate audio ≥ 2 minutes before slot (TZ §13 risk mitigation).

### Product — Music (TZ §3.2)

- R23. Yandex Music server-side proxy; token never exposed to browser.
- R24. Playlist rules in `services/music/playlist_rules.yaml` — sole developer-editable music policy file (replaces `playlist-rules.js`).
- R25. `/order` resolves track by title/artist → MUSIC_ORDER for operator's city.
- R26. `/playlist <name>` (admin) updates playlist rules for operator's city.

### Product — Ads & Bot (TZ §3.3, §3.4)

- R27. Voice OGG → MP3 128kbps, EBU R128; enqueue AD after operator confirms city.
- R28. Bot commands: voice ads, `/order`, `/playlist`, `/city`, `/city all`, `/status` — with confirmation on enqueue actions.
- R29. `/status`: current track, next 5 queue items, time until next news.

### API (TZ §7 — adapted)

- R30. Public: `GET /api/geo/detect`, `GET /api/geo/reverse`, `GET /api/now-playing/{cityTag}`, `GET /api/queue/{cityTag}`, `GET /api/health`.
- R31. Stream: ICY via Icecast `/{cityTag}` (not HLS/WS from TZ §7.1).
- R32. Internal: `POST /api/bot/webhook`, `POST /internal/enqueue`, ads submit API.
- R33. Server-side only: Yandex, TTS, Telegram, news fetcher, GigaChat summarizer.

### Data & Cron (TZ §8, §9)

- R34. PostgreSQL tables: `news_items`, `ads`, `tracks_cache`, `playlist_config`, `broadcast_log`.
- R35. Redis keys per TZ §8.2 plus `fm21:news:played:{hash}`, `fm21:playlist:buffer:{cityTag}`.
- R36. Cron: news enqueue `*/15`; playlist refresh hourly; cache cleanup 03:00; news play_count reset midnight.

### Production (TZ §11 stage 6, §10)

- R37. Multi-city from `broadcast/liquidsoap/cities.yaml` without code changes per city.
- R38. Production deploy with HTTPS Telegram webhook.
- R39. Health/monitoring; public health does not leak internal topology.
- R40. Env vars per TZ §10 (adapted: `DATABASE_URL`, `REDIS_URL`, provider keys).

---

## Key Flows

### F1. Listener session (TZ §6.3)

1. Load player → detect city → show badge
2. User taps Play → ICY stream from `/{cityTag}`
3. Poll now-playing every 5s; audio survives metadata outage
4. City change → reconnect to new mount live edge

### F2. Voice ad (TZ §3.3, §3.4)

1. Operator sends voice → inline city keyboard (default from `/city`)
2. Confirm city → transcode → persist ad → injector AD enqueue
3. Plays after current block on target city mount only

### F3. Music order (TZ §3.4)

1. `/order Title — Artist` → Yandex search → inline confirm
2. Enqueue MUSIC_ORDER for operator city
3. Plays after ADs and NEWS_PAIR, before MUSIC filler

### F4. News cycle (TZ §3.1)

1. Fetch cron ingests RSS → `news_items` deduped by URL
2. T−2 min: select item → summarize → TTS → ready
3. `:00/:15/:30/:45`: NEWS_PAIR enqueue all cities → increment play_count once
4. Liquidsoap plays stinger + news atomically

---

## Acceptance Examples

- AE1. Moscow AD not heard on SPB stream (TZ §12 геотаргетинг).
- AE2. AD submitted during news block waits until NEWS_PAIR completes (TZ §12 очередь).
- AE3. News at play cap selects different item; repeat uses cached MP3 (TZ §12 новости).
- AE4. Geo denied → badge + Play without modal.
- AE5. Late joiner misses past bot order (sync radio).
- AE6. Background tab 10 min — audio continues.
- AE7. Full TZ §12 bot: voice, `/order`, `/playlist`, `/city` with confirmation.
- AE8. Music fills air; playlist rules change without broadcast core edits.
- AE9. News every 15 min with stinger; duration 1–2 min.

---

## Scope Boundaries

### In scope (this product)

- Complete TZ §1–§4, §6–§9, §12 behavior
- Two+ cities at launch; extensible to N via `cities.yaml`
- Closed-beta Yandex OAuth music
- PostgreSQL persistence
- Production HTTPS deploy

### Deferred for later

- Commercial music licensing for public launch (ADR-002 production path)
- HLS adaptive bitrate as primary transport
- WebSocket audio delivery
- Listener accounts
- Web admin dashboard (Telegram remains control plane)
- Per-listener personalized manifests

### Outside product identity

- Custom Node.js broadcast engine
- Client-side Web Audio segment stitching
- Host-native Python/Node/ffmpeg/Liquidsoap installs

### Superseded from TZ (implementation only)

- Node.js service layout (`news-fetcher.js`, `queue` in browser)
- HLS `/api/stream/.../manifest.m3u8` and WS audio
- Web Audio crossfade/prefetch client mux
- Separate `NEWS_STINGER` + `NEWS` enqueue types
- `playlist-rules.js` → `playlist_rules.yaml`

---

## Dependencies / Assumptions

- Telegram bot token and HTTPS webhook URL available for production
- Yandex Music personal token for closed beta
- GigaChat API (`GIGACHAT_CREDENTIALS`, optional `GIGACHAT_SCOPE`) for summarization; Neurozvuk (or equivalent) for TTS
- MaxMind GeoLite2 or equivalent for GeoIP
- S3 or local filesystem for news MP3 storage (prod vs dev)
- Human approves: ADR-004+ news sourcing, production `sources.yaml`, secrets, production city list

---

## Outstanding Questions

### Resolved in this brainstorm

- **Q1:** Stack = Liquidsoap/Icecast + Python + PostgreSQL + Redis + Docker (not Node).
- **Q2:** Player = ICY `<audio>` + metadata HTTP (not HLS/WS from TZ).
- **Q3:** Full TZ product is the target; geo slice is Phase 1 only, not the end state.
- **Q4:** `NEWS_PAIR` atomic; play_count global per news item (all cities share same news audio).
- **Q5:** News slot timezone = UTC wall clock unless ADR-010 pins Europe/Moscow (default UTC for cron).

### Deferred to planning (ADR detail)

- Exact RSS source list in `sources.yaml` (human gate)
- S3 vs local `file://` for prod news audio (ADR-008)
- Production orchestrator: single-VM compose-prod vs K8s (U34)

---

## Sources

- `docs/tz.md` v1.1 — product authority for behavior
- `docs/adr/001-delivery-model.md`, `002-music-licensing.md`, `003-container-strategy.md` — retained architecture
- `docs/contracts/` — behavior contracts (align with this doc; update if gaps found during implementation)
