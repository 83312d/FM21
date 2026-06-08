---
name: FM21
last_updated: 2026-06-08
---

# FM21 Strategy

## Target problem

City listeners want local internet radio—music, news, and voice ads tuned to where they are—but most streaming products treat everyone as an individual playlist. Operators need to reach a city without building a custom broadcast stack, while licensing and sync semantics (one shared timeline per city) make naive “stitch audio in the browser” approaches risky and hard to ship.

## Our approach

Server-side synchronous radio per `city_tag`: Liquidsoap + Icecast own the queue and crossfade; listeners use standard ICY playback with metadata on a separate channel. Operators control the air via Telegram; behavior is specified in contracts and acceptance examples so agents implement against docs, not ad-hoc re-reads of the legacy brief.

**Delivery:** Monorepo; every component ships as a Docker image (dev, CI, staging, production). Docker Compose orchestrates local development only—the same images deploy elsewhere without Compose (ADR-003).

## Who it's for

**Primary:** City listener — opens the web player with no account, hears the live stream for their city, and can override detection via badge or URL.

**Secondary:** Telegram operator — posts voice ads and (later) music orders for a chosen `city_tag` without touching infrastructure.

## Key metrics

- **Active listeners per city** — concurrent ICY connections per mount (`moscow`, `spb`, …); Icecast stats or proxy logs
- **Ad enqueue rate** — voice ads accepted per city per day; injector / bot logs
- **Stream uptime** — percentage of time each city mount serves continuous audio without dead air > 5s; health checks + Icecast

## Tracks

### Phase 0 — Agent-ready foundation

Strategy, `AGENTS.md`, ADRs, behavior contracts, and machine-verifiable acceptance spec before broadcast code.

_Why it serves the approach:_ Agents and humans share one contract surface; `docs/tz.md` stays historical brief only.

### Phase 1 — Geo vertical slice

Two cities (Moscow, Saint Petersburg), static music bed, Moscow-only voice ad from Telegram; web player with geo badge and ICY playback—all runnable via `docker compose up`.

_Why it serves the approach:_ Proves geotargeting—the highest product risk—before Yandex, news, and TTS integrations.

### Phase 2 — Music (closed beta)

Yandex Music via personal OAuth behind a `MusicProvider` seam; playlist rules in config, not broadcast core.

_Why it serves the approach:_ Music policy changes without touching Liquidsoap queue semantics (R31).

### Phase 3 — News pipeline

15-minute slots, stinger+news atomic pairs, TTS, play-count limits.

_Why it serves the approach:_ Fills the product vision after geo and music paths are proven.

### Phase 4 — Production hardening

`deploy/` manifests (non-Compose), PostgreSQL, monitoring, multi-city ops, licensing path for public launch.

_Why it serves the approach:_ Same container images from Phase 1; production orchestration without rewriting services.

## Not working on

- Custom Node.js broadcast engine or client-side Web Audio segment stitching
- Per-listener personalized manifests (on-demand model)
- Listener authentication or web-only operator UI
- HLS/WebSocket as primary audio transport for Phase 1 (ICY sync radio first)
- Host-installed Python, Node, ffmpeg, or Liquidsoap for project workflows (Docker only)

## Marketing

**One-liner:** FM21 is geotargeted internet radio—one live timeline per city, controlled from Telegram.

**Key message:** Like FM for your city: shared queue, local ads, continuous music and news. Open the player and listen; operators shape the air from chat.
