# Listener Contract

**Authority:** Implement web player (`web/`), geo API (`services/geo/`), and metadata API (`services/metadata/`) against this document. Supersedes `docs/tz.md` §6.3–6.4 for implementation.

**Requirements:** R1, R4, R11–R17, R37  
**ADR:** [ADR-001](../adr/001-delivery-model.md)

---

## 1. Scope

Defines listener-facing behavior:

- City detection and override
- Stream connection (ICY live edge)
- Player controls and persistence
- Now-playing metadata
- Sync-radio UX expectations

Out of scope: operator Telegram flows, queue internals, music licensing.

---

## 2. Access model

- **No authentication** (R11). Any visitor can play.
- **Play button required** before audio starts (R12) — browsers block autoplay without user gesture.
- **Volume** 0–100%, persisted in `localStorage` key `fm21_volume` (R13).

---

## 3. City detection order (R1)

On player load, resolve `city_tag` in strict order:

```
1. URL query ?city={tag}     — if present and valid, use it
2. localStorage fm21_city    — if present and valid, use it
3. navigator.geolocation     — if user grants (timeout 5s)
   → GET /api/geo/reverse?lat=&lon=
4. GET /api/geo/detect       — IP-based GeoIP fallback
5. DEFAULT_CITY_TAG env      — typically moscow
```

**Valid tags:** active entries from `broadcast/liquidsoap/cities.yaml` — canonical city list for broadcast, geo validation, and player (Phase 1: `moscow`, `spb`). Geo service reads the same file; do not maintain a separate city config.

After resolution, persist chosen tag to `localStorage.fm21_city` (unless URL override is ephemeral — implementation may always persist last explicit user choice).

### Badge UX (R4, FG2)

- Show human-readable city name on badge (e.g. «Москва», «Санкт-Петербург»).
- Provide visible **change control** (dropdown or tap-to-change) — listener can correct wrong detection.
- **No blocking confirmation modal** before Play. Detection may complete asynchronously; Play is available as soon as minimum UI is ready (default city or detected city).
- If geolocation denied and IP confidence low, still show best-effort city with change control (AE4).

---

## 4. Stream connection (R2, KTD-2)

### URL pattern

```text
{audio_src} = {ICECAST_BASE}/{cityTag}
```

Development example: `http://localhost:8000/moscow`

Use HTML5 `<audio>` element — **not** Web Audio API segment stitching, not WebSocket audio (ADR-001).

### City switch (FG7)

When listener changes city (badge, URL, or storage):

1. **Immediately** disconnect current `<audio>` source.
2. Set `src` to new mount `/{newCityTag}`.
3. If playback was active, call `play()` on new source. If the browser rejects `play()` (autoplay policy after background tab or new `src`), show a non-blocking **«Нажмите Play»** prompt on the player — do not use a modal.
4. Reconnect completes within **2 seconds** under normal network conditions when `play()` succeeds.
5. Listener hears **live edge** of new city — not a rewind to block start.

### Background tab (R16, AE6)

Audio continues when `document.hidden` for extended periods (10+ minutes). Do not pause on visibility change. Metadata polling may slow when hidden; audio must not stop.

---

## 5. Synchronous radio UX (FG3, AE5)

All listeners on a mount share the same timeline:

- **Late joiner** hears whatever is **currently playing** — mid-block entry is normal.
- Content that **already finished** before connect is **not** replayed.
- Bot-ordered tracks heard only if still queued or currently airing when listener connects.

Optional player copy (not blocking): «Общий эфир — вы подключаетесь к прямому эфиру города».

---

## 6. Now playing (R14, KTD-3)

**OpenAPI:** [docs/openapi.yaml](../openapi.yaml) — `GET /api/now-playing/{cityTag}`.

- Poll `GET /api/now-playing/{cityTag}` every **5 seconds** while playing.
- Display: title, artist (if applicable), content type label: `music` | `news` | `ad`.
- If metadata API fails, keep audio playing; show last known or placeholder text.
- Metadata channel is independent of audio stream — audio survives metadata outage.

---

## 7. Visual identity (R17)

CSS variables (from legacy brief, still binding):

```css
:root {
  --fm21-accent: #44EB99;
  --fm21-primary: #861BE3;
  --fm21-bg: #0d0d12;
  --fm21-text: #ffffff;
}
```

- Logo / branding: FM21 gradient accent → primary.
- «В эфире» live indicator: pulsing dot when playback active.

---

## 8. Geo API responses

**OpenAPI:** [docs/openapi.yaml](../openapi.yaml) — `GET /api/geo/detect`, `GET /api/geo/reverse`.

### `GET /api/geo/detect`

Response:

```json
{
  "city_tag": "moscow",
  "city_name": "Москва",
  "source": "geoip"
}
```

`source`: `geoip` | `reverse` | `default`

### `GET /api/geo/reverse?lat={}&lon={}`

Same shape; `source`: `reverse` or `default` on failure.

Missing GeoIP database → `source: "default"`, `city_tag` from `DEFAULT_CITY_TAG` — graceful degradation, no error screen.

---

## 9. Acceptance mapping

Machine-verifiable entries: [spec/acceptance.yaml](../../spec/acceptance.yaml).

| Example | Spec ID | Sections |
|---------|---------|----------|
| AE4 — Badge without modal, Play available | [AE4](../../spec/acceptance.yaml) | §3 |
| AE5 — Late joiner misses past orders | [AE5](../../spec/acceptance.yaml) | §5 |
| AE6 — Background playback | [AE6](../../spec/acceptance.yaml) | §4 |
| City switch reconnect | [AE-CITY-SWITCH](../../spec/acceptance.yaml) | §4 |
| R37 — Detect, badge, correct mount, now-playing | [AE4](../../spec/acceptance.yaml), [AE-CITY-SWITCH](../../spec/acceptance.yaml), [AE-NOW-PLAYING](../../spec/acceptance.yaml) | §3, §4, §6 |

---

## 10. Transport and privacy

- **Production TLS:** all listener-facing paths use HTTPS — gateway APIs (`/api/geo/*`, `/api/now-playing/*`) and public stream URLs. Dev `http://localhost` examples are not production patterns.
- **Geo data:** do not persist raw lat/lon or client IP beyond request scope. Log only resolved `city_tag` and `source`. Reverse geocoding uses server-side lookup; coordinates are not stored.

## 11. Stream errors

If the ICY mount fails to connect or returns HTTP errors, keep the player UI usable: show a recoverable error state with **retry** (exponential backoff, max 30 s). Do not silently stall on a broken `src`. Metadata outage handling (§6) is separate — audio may continue while metadata fails.

## 12. Explicit non-goals

- HLS manifest or WebSocket audio in Phase 1
- Listener accounts or saved playlists
- Per-listener queue preview on public API (operator `/status` only)
- Blocking geo consent modal
- Full WCAG audit in Phase 1 (baseline a11y: keyboard-focusable Play, labeled city control — detailed in U7)
