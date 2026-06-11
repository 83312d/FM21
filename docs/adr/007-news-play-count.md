# ADR-007: News play-count semantics

**Status:** Accepted (Path A assumptions, 2026-06-11)  
**Date:** 2026-06-11  
**Deciders:** Product owner  
**Requirements:** R8, AE3

## Context

The same news story may air on multiple 15-minute slots and both city mounts. Repeat policy must cap listener fatigue while allowing cached audio reuse without re-TTS.

## Decision

### 1. Limit: ≤ 3 plays per 24 hours per story

- `news_items.play_count` increments **once per air slot** after fan-out to all cities succeeds (U21).
- Eligible for selection only when `play_count < 3` and `status = ready`.

### 2. PostgreSQL is source of truth

- `play_count` and `last_played_at` on `news_items`.
- Repository `increment_play_count` only when `status = ready`.

### 3. Redis mirror for fast selection

- Key `fm21:news:played:{content_hash}` with TTL **86400** seconds.
- Set/increment on air; used by selection (U19) to skip over-played items without heavy PG scans.

### 4. Midnight reset

- Cron `news-play-count-reset` at `0 0 * * *` (UTC) resets PG `play_count` to 0 for items played in the prior window and clears expired Redis keys.
- AE3: third play within 24h uses **cached MP3** — no new TTS call.

## Consequences

- Fan-out failure before all cities accept must not increment play_count.
- Timezone for reset is UTC unless ADR-010 amended for Europe/Moscow.
