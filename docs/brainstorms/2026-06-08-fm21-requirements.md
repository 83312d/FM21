---
date: 2026-06-08
topic: fm21
---

# Requirements: FM21 — Geotargeted Internet Radio

## Summary

FM21 is an autonomous internet radio where listeners hear continuous music, IT news every 15 minutes, and city-targeted voice ads — controlled by operators through Telegram, with no listener authentication. Development starts with documentation, architectural decisions, and an agent-native workflow (compound-engineering), then delivers a vertical proof of geotargeting (two cities, one ad) before expanding to full integrations.

---

## Problem Frame

`docs/tz.md` describes a complete product vision but embeds implementation choices (custom broadcast engine, client-side audio stitching, a specific server stack) that were never validated against licensing, streaming semantics, or greenfield delivery risk. The repo has no application code, no agent onboarding docs, and no recorded architectural decisions — every Cursor session would otherwise re-derive intent from a 300-line spec.

The highest-risk gaps are: (1) geotargeting is the headline rule but was sequenced last in the original delivery plan; (2) music licensing via unofficial Yandex APIs is not shippable for public radio; (3) sync vs async broadcast semantics are mixed in the spec; (4) agents have no structured contracts to implement against.

---

## Key Decisions

**Synchronous radio per city.** All listeners sharing a `city_tag` hear the same content at the same time — like FM radio, not a personal playlist. A song ordered via bot enters the city's shared queue; a listener who starts later may miss it. This matches `docs/tz.md` §1 («заказ попадает в очередь всех слушателей города») and implies server-side broadcast, not per-listener client stitching.

**Server-side broadcast spine (Liquidsoap + Icecast).** Queue management, crossfade, and stream generation live on the server. Each active `city_tag` gets its own broadcast mount. The web player uses standard streaming playback; metadata (now playing, queue preview) arrives separately. Custom broadcast engine and Web Audio segment stitching from `docs/tz.md` are out of scope.

**Music: Yandex via personal OAuth for closed beta only.** Unofficial Yandex Music API with a personal subscription token is acceptable for friends-only / closed beta; ToS and licensing risk is explicitly accepted. Public launch requires a separate licensing path (ADR-002 documents beta vs production). Royalty-free catalog remains a fallback if Yandex integration breaks.

**Contract-first documentation.** Product behavior is split into three contracts (Broadcast Semantics, Listener Contract, Operator Contract) plus acceptance criteria derived from `docs/tz.md` §12. `docs/tz.md` remains the source brief; contracts become the agent-facing spec.

**Vertical geo slice before linear phases.** First deliverable proves geotargeting: Moscow + Saint Petersburg, static music bed, one Moscow-only voice ad from Telegram. News, TTS, and music provider integrations follow only after geo isolation is demonstrated.

**Compound-engineering agent workflow.** Product development follows: strategy doc → brainstorm (this document) → plan → work → code review → compound learnings. Human gatekeeps architectural ADRs, secrets, and playlist policy config.

**Containers everywhere; Compose for dev only.** All FM21 services ship as Docker images built from the monorepo. Local development and CI run exclusively via Docker (Compose orchestrates dev; staging/production use the same images without Compose — see ADR-003). Host installs of Python, Node, ffmpeg, or Liquidsoap are not supported.

---

## Actors

- **A1. Listener** — opens the web player, hears the city stream, no account required
- **A2. Operator** — manages content via Telegram bot (ads, song orders, playlist, city tag)
- **A3. Admin** — configures playlist rules, manages bot permissions
- **A4. System** — autonomous services: news generation, music buffering, broadcast engine, geo detection

---

## Requirements

### Product — Geotargeting

- R1. On player start, the system determines the listener's `city_tag` via geolocation (with consent) → reverse geocoding, with IP-based fallback, and supports manual override via URL parameter and persistent local storage.
- R2. Each `city_tag` has an isolated broadcast queue and stream. Content tagged for city A is never audible on city B's stream.
- R3. `city_tag = "all"` delivers globally targeted content heard by every listener regardless of detected city.
- R4. The listener sees a city badge on the player and can change city before or during playback; there is no blocking confirmation modal — Play is available immediately after detection.

### Product — Broadcast Semantics

- R5. Queue item types and priority order: voice ads (highest) → news stinger → news → bot-ordered music → regular playlist music (lowest).
- R6. No item interrupts the currently playing block. New items enqueue after the current block ends.
- R7. News slots fire every 15 minutes per city stream, preceded by a 3–5 second «Сейчас новости» stinger, followed by a 1–2 minute voiced news segment.
- R8. Each news item plays at most 3 times per 24 hours; repeated plays reuse cached text and audio without re-synthesis.
- R9. Voice ads: max 60 seconds, max 5 pending per city queue; play only for the targeted `city_tag`.
- R10. Music fills all time not occupied by ads, news, or ordered tracks.

### Product — Listener Experience

- R11. Open access — no listener authentication.
- R12. Mandatory play/pause control to satisfy browser autoplay policies.
- R13. Volume control 0–100%, persisted across sessions.
- R14. Now-playing display shows title, artist, and content type (music / news / ad).
- R15. City badge shows the listener's active city name.
- R16. Playback continues when the browser tab is backgrounded (Chrome, Firefox, Safari).
- R17. Visual identity uses accent `#44EB99` and primary `#861BE3` on dark background.

### Product — Operator (Telegram Bot)

- R18. Operators send voice messages to create geo-targeted ads; the bot confirms target city before enqueueing.
- R19. `/order <title> — <artist>` searches the music catalog, confirms match, and enqueues for the operator's `city_tag`.
- R20. `/city <tag>` sets the operator's default city for ads and orders; `/city all` enables global targeting.
- R21. `/playlist <name>` changes playlist rules (admin only).
- R22. `/status` shows current track, queue preview, and time until next news for the operator's city.

### Pre-Development — Documentation & Specs

- R23. `STRATEGY.md` defines target problem, approach, persona, metrics, and delivery tracks.
- R24. `AGENTS.md` (~100 lines) serves as a table of contents pointing to strategy, contracts, ADRs, plans, and solutions — not a duplicate of the full spec.
- R25. Three behavior contracts are written before implementation code: Broadcast Semantics, Listener Contract, Operator Contract.
- R26. Acceptance criteria from `docs/tz.md` §12 are captured as verifiable examples linked to requirement IDs.
- R27. Architectural decisions are recorded as ADRs in `docs/adr/`; ADR-001 (delivery model), ADR-002 (music licensing), and ADR-003 (container strategy) exist before broadcast or music code.

### Pre-Development — Agent Workflow

- R28. Development phases are vertical slices (geo proof → music → news → bot → production), not horizontal layers.
- R29. After each delivered slice, learnings are captured in `docs/solutions/` via compound workflow.
- R30. Agents implement against contracts and acceptance examples; they do not modify live runtime state (queues, Redis) — only operators and deployed services do.
- R31. Playlist selection rules are the sole developer-editable music policy surface; core broadcast logic does not change when playlists change.

### Delivery — Phase 0 (before code)

- R32. ADR-001 records the delivery model decision (sync multi-mount broadcast).
- R33. ADR-002 records the music licensing path for MVP and production trajectory.
- R34. Contracts and acceptance examples are reviewed before `ce-plan` generates an implementation plan.

### Delivery — Infrastructure

- R38. Every FM21 component (broadcast spine, glue services, web assets, test runners) ships as a Docker image; developers and CI do not install language runtimes or ffmpeg on the host.
- R39. `docker-compose.yml` orchestrates the local development stack only; staging and production deploy the same images with environment-specific configuration, not root Compose.

### Delivery — Phase 1 (geo vertical slice)

- R35. Two city streams (Moscow, Saint Petersburg) broadcast continuous audio from a static catalog.
- R36. A voice ad sent via Telegram for Moscow is audible on Moscow's stream and absent from Saint Petersburg's stream.
- R37. Web player detects city, displays badge, plays the correct mount, shows now-playing metadata.

---

## Key Flows

- F1. **Listener starts playback**
  - **Trigger:** Listener opens the site and taps play
  - **Actors:** A1, A4
  - **Steps:** Detect city (override → geolocation → IP) → show badge → connect to city's stream → begin playback → update now-playing via metadata channel
  - **Covered by:** R1, R4, R11–R16, R37

- F2. **Operator posts a voice ad**
  - **Trigger:** Operator sends voice message to Telegram bot
  - **Actors:** A2, A4
  - **Steps:** Bot prompts city confirmation → transcode and normalize audio → enqueue at highest priority after current block → stream plays ad for matching city only
  - **Covered by:** R5, R6, R9, R18, R36

- F3. **News cycle**
  - **Trigger:** 15-minute schedule fires for a city
  - **Actors:** A4
  - **Steps:** Select eligible news item → enqueue stinger then news after current block → increment play count → cache audio for repeats
  - **Covered by:** R7, R8, R10

- F4. **Operator orders a song**
  - **Trigger:** `/order` command with title and artist
  - **Actors:** A2, A4
  - **Steps:** Search catalog → show match for confirmation → enqueue at order-music priority for operator's city → all current listeners of that city hear it in shared timeline order
  - **Covered by:** R5, R6, R19, synchronous radio decision

---

## Acceptance Examples

- AE1. **Covers R2, R36.** **Given** streams for `moscow` and `spb` are live, **When** an operator enqueues a voice ad for `moscow`, **Then** a listener on the Moscow stream hears the ad after the current block ends, and a listener on the Saint Petersburg stream does not.

- AE2. **Covers R5, R6.** **Given** a news segment is playing, **When** a voice ad is submitted, **Then** the ad waits in queue and plays only after the news block completes — no interruption.

- AE3. **Covers R7, R8.** **Given** a news item has played 3 times in the last 24 hours, **When** the 15-minute news slot fires, **Then** a different eligible news item is selected; if the same item must repeat, cached audio is reused without new TTS.

- AE4. **Covers R1, R4.** **Given** a listener denies geolocation and IP resolves to Moscow with low confidence, **When** the player loads, **Then** the city badge shows «Москва» with a visible change control; Play is available without a blocking modal.

- AE5. **Covers synchronous radio decision.** **Given** Ivan orders a song at 14:03 on Moscow stream, **When** Petya starts listening at 14:05, **Then** Petya does not hear Ivan's order unless it is still queued and not yet played.

- AE6. **Covers R16.** **Given** playback is active, **When** the user switches to another tab for 10 minutes, **Then** audio continues without requiring re-interaction.

---

## Success Criteria

- Geo vertical slice (Phase 1) demonstrable in a browser with two cities and one targeted ad — stakeholder can verify isolation without reading logs.
- All §12 acceptance criteria from `docs/tz.md` traceable to requirement IDs and acceptance examples.
- `ce-plan` can produce an implementation plan without inventing user behavior — contracts and this doc supply it.
- Agent sessions start from `AGENTS.md` + contracts, not from re-parsing `docs/tz.md` each time.

---

## Scope Boundaries

### Deferred for later

- Yandex Music for production/public launch (closed beta uses personal OAuth per ADR-002)
- B2B licensed music providers (Feed.fm, etc.)
- Full IT news pipeline (RSS fetch, summarization, TTS) — after geo slice
- Multi-city production scaling, monitoring, CDN
- HLS adaptive bitrate (ICY or basic HLS sufficient for MVP)
- Personalized per-listener manifests (Super Hi-Fi model)
- WebSocket audio delivery

### Outside this product's identity

- Listener accounts and authentication
- Web-only operator control (Telegram is the control plane)
- Live call-in / WebRTC interactivity
- Podcast-on-demand (this is linear radio, not on-demand)
- Custom Node.js broadcast engine with client-side Web Audio stitching (replaced by server-side spine)

---

## Dependencies / Assumptions

- Operators have Telegram accounts and the bot is added to their workflow.
- A Yandex Music account with OAuth token is available for closed-beta streaming; operators understand this is not licensed for public commercial radio.
- TTS provider with Russian language support is available for news phase (Neurozvuk or equivalent).
- GeoIP database (MaxMind GeoLite2 or equivalent) available for IP fallback.
- Hosting runs FM21 as Docker containers (ADR-003); Liquidsoap + Icecast are never installed directly on the host.
- Compound-engineering plugin remains enabled in Cursor for agent-assisted development.

---

## Outstanding Questions

### Resolve before planning

_All resolved._

- **Q1:** Yandex personal OAuth for closed beta; public launch needs separate licensing (ADR-002).
- **Q2:** City badge with change control; no blocking confirmation modal before Play.

### Deferred to planning

- Exact glue-service language (Go vs Python) for news/bot/geo APIs
- Hosting topology (single VM vs containers per city)
- TTS provider selection and cost model at 15-minute cadence × N cities
- Icecast vs HLS as primary listener protocol (ICY recommended for sync radio low latency; planning decides)

---

## Sources / Research

- `docs/tz.md` — original product brief (v1.1)
- `docs/ideation/2026-06-08-fm21-predev-ideation.md` — pre-development ideation survivors
- [compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin) — agent workflow (strategy → brainstorm → plan → work → compound)
- Liquidsoap / Icecast — proven autonomous internet radio pattern with queue injection
- Yandex Music — no official commercial streaming API; personal OAuth not suitable for public radio
