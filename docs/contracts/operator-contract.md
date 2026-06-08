# Operator Contract

**Authority:** Implement Telegram bot (`services/bot/`), transcode pipeline, and injector integration against this document. Supersedes `docs/tz.md` §3.3–3.4 for implementation.

**Requirements:** R9, R18–R22, R36  
**ADR:** [ADR-001](../adr/001-delivery-model.md), [ADR-002](../adr/002-music-licensing.md)

---

## 1. Scope

Defines operator (Telegram user) interactions:

- Voice ad creation with geo confirmation
- City default and global mode
- Queue limits and rejection behavior
- Command surface by phase

Out of scope: listener player UI, Liquidsoap dequeue logic (see [Broadcast Semantics](broadcast-semantics.md)).

---

## 2. Transport

- **Control plane:** Telegram only — no web admin for operators in Phase 1.
- **Webhook:** `POST /api/bot/webhook` (server-side, HTTPS in production). Reject requests missing or mismatching `X-Telegram-Bot-Api-Secret-Token` before any handler logic.
- **Library:** `python-telegram-bot` (or equivalent) in bot container.

Operators must have Telegram account and access to the bot. **Phase 1 dev:** open bot access is acceptable on localhost. **Production:** require `TELEGRAM_OPERATOR_IDS` allowlist before publishing a public bot username.

---

## 3. Operator city context

Each operator has a **default `city_tag`** stored per Telegram user ID.

| Command | Behavior |
|---------|----------|
| `/city <tag>` | Set default to `<tag>` (`moscow`, `spb`, …) |
| `/city all` | Set default to global mode — next ads fan-out to all cities |
| (no prior `/city`) | Default `moscow` for Phase 1 dev; production default from env `DEFAULT_OPERATOR_CITY` if set |

Default applies to:

- Voice ads (unless overridden at confirm step)
- `/order` (Phase 2+)
- `/status` (Phase 2+)

---

## 4. Voice ad flow (R18, R36)

**Trigger:** Operator sends voice message (OGG Opus).

### Steps

```
1. Bot receives voice message
2. Bot checks duration ≤ 60 seconds — if over, reply with rejection (do not transcode)
3. Bot sends inline keyboard: city choices (active cities + «Все города» for all)
4. Operator taps confirmation
5. Bot replies «Обрабатываю…» (processing) — transcode may take several seconds
6. Bot transcodes: OGG → MP3 128kbps, EBU R128 loudness normalization (ffmpeg in container)
7. Bot saves to data/ads/{id}.mp3
8. Bot POST /internal/enqueue { type: AD, uri, city_tag, meta } with `X-FM21-Internal-Token`
9. Bot replies success with city name(s) or error (queue full, etc.)
```

### Geo confirmation

- Operator **must** confirm city via inline button — voice alone does not enqueue.
- «Все города» maps to `city_tag: "all"` (fan-out per Broadcast Semantics §5).
- Moscow-only proof (Phase 1 / AE1): operator confirms «Москва» → only `fm21:queue:moscow` receives item.

### Limits (R9)

| Limit | Value | Operator feedback |
|-------|-------|-------------------|
| Max duration | 60 s | «Слишком длинное сообщение (макс. 60 сек)» |
| Max pending AD per city | 5 | «Очередь объявлений для {city} заполнена» (injector 409) |

**Sixth ad (R9):** When 5 AD items already pending for target city, injector returns 409 — bot surfaces message, does not enqueue.

### Transcode failure

If ffmpeg missing or fails: reply «Не удалось обработать аудио. Попробуйте ещё раз.», no partial enqueue.

---

## 5. Command reference by phase

### Phase 1 (geo slice)

| Input | Behavior |
|-------|----------|
| Voice message | §4 flow |
| `/city <tag>` | §3 |
| `/city all` | §3 |
| `/order …` | Reply: «Скоро» / coming soon |
| `/status` | Reply: «Скоро» |
| `/playlist …` | Reply: «Скоро» (admin check deferred) |

### Phase 2+ (music)

| Command | Behavior |
|---------|----------|
| `/order <title> — <artist>` | Search Yandex via `MusicProvider` → show match → confirm → enqueue `MUSIC_ORDER` for operator default city |
| `/status` | Current track, queue preview (next 5), time until next news for operator's city |

### Phase 2+ (admin)

| Command | Behavior |
|---------|----------|
| `/playlist <name>` | Admin only (`TELEGRAM_ADMIN_IDS`) — update `playlist_rules.yaml` / Redis rules for city |

---

## 6. Enqueue integration

Bot never writes Redis directly — calls injector `POST /internal/enqueue`.

Example success path:

```json
POST /internal/enqueue
{
  "type": "AD",
  "uri": "file:///data/ads/7f3a.mp3",
  "city_tag": "moscow",
  "meta": {
    "title": "Voice ad",
    "artist": "",
    "duration_sec": 38
  }
}
```

Response 201 → bot confirms to operator.  
Response 409 → bot reports queue full.  
Response 400 → bot reports invalid input.

---

## 7. Permissions

| Role | Capabilities |
|------|--------------|
| Operator | Voice ads, `/city`, `/order`, `/status` |
| Admin | Above + `/playlist` |

Admin list: `TELEGRAM_ADMIN_IDS` env (comma-separated Telegram user IDs).

Phase 1 dev: all users with bot access treated as operators; admin commands stubbed. Production requires `TELEGRAM_OPERATOR_IDS` (see §2).

---

## 8. Acceptance mapping

Machine-verifiable entries: [spec/acceptance.yaml](../../spec/acceptance.yaml).

| Example | Spec ID | Sections |
|---------|---------|----------|
| AE1 — Moscow ad, SPB silent | [AE1](../../spec/acceptance.yaml) | §4, §6 |
| AE2 — Ad after current block | [AE2](../../spec/acceptance.yaml) | Broadcast Semantics (bot only enqueues; no interrupt) |
| Sixth ad rejected | [AE-QUEUE-FULL](../../spec/acceptance.yaml) | §4 limits |
| `all` fan-out | [AE-ALL-FANOUT](../../spec/acceptance.yaml) | §3, §4 |
| R18 — City confirm before enqueue | AE1, AE-ALL-FANOUT | §4 |

---

## 9. Explicit non-goals (Phase 1)

- Web dashboard for queue inspection
- Manual Redis LPUSH by operators
- Text ads (voice only in Phase 1)
- Rate limiting (deferred to U11 production hardening — minimum: per-IP on webhook and geo APIs, per-operator daily ad cap)
