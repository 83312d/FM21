# ADR-010: News slot timezone & slip

**Status:** Accepted (Path A assumptions, 2026-06-11)  
**Date:** 2026-06-11  
**Deciders:** Product owner  
**Requirements:** R21, ADR-001 §8

## Context

News airs every 15 minutes per city. Materialize runs T−2 min; enqueue at slot boundaries. Backlog from ads must not delay news indefinitely.

## Decision

### 1. Cron timezone: UTC

- All news cron schedules in `docker-compose.yml` use **UTC wall clock**:
  - Materialize: `:02, :17, :32, :47` each hour
  - Enqueue: `:00, :15, :30, :45` each hour
  - Fetch: `*/10 * * * *`
  - Play-count reset: `0 0 * * *`
- Europe/Moscow alignment deferred — operators accept UTC slot times for closed beta.

### 2. Ten-minute slip skip (ADR-001 §8)

- When enqueue cron fires, if pending higher-priority backlog would push news **> 10 minutes** past the scheduled slot, **skip the slot** and log.
- News does not preempt current block or jump ahead of pending ads.

### 3. Slot pin in Redis (U20)

- Materialize pins `fm21:news:slot:{city}:{slot_iso}` so enqueue at T uses the same story per city.

## Consequences

- Listener-facing "every 15 min" is UTC-aligned unless cities.yaml gains timezone metadata later.
- Manual demo may require waiting for UTC boundary or triggering cron manually.
