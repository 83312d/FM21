---
module: news
date: 2026-06-11
problem_type: architecture_pattern
component: services/news, broadcast/liquidsoap, docker-compose
symptoms:
  - "Live RSS fetch fails SSL CERTIFICATE_VERIFY_FAILED against Habr/3DNews from container"
  - "Syndicated stories deduped by content_hash fail when RSS snippet is HTML vs fetched article text"
  - "Empty RSS snippets create unfilled fetched rows that block summarizer"
  - "GigaChat/SaluteSpeech need Russian CA or verify flag in Docker"
root_cause: "Path A ADR assumptions; RSS text normalization mismatch; no minimum body guard on ingest; Sber APIs use certs not in default Debian CA bundle."
resolution_type: pattern
tags: [news, gigachat, salutespeech, rss, phase-3, ae2, ae3]
---

# Phase 3: News pipeline — ingest, materialize, enqueue

## Problem

Phase 3 adds RSS → GigaChat summary → SaluteSpeech TTS → 15-minute NEWS_PAIR slots per city with play_count cap (AE3) and no-interrupt during news blocks (AE2).

## Patterns

### 1. UTC slot clock (ADR-010)

| Cron | UTC minutes | Role |
|------|-------------|------|
| `news-fetch` | `*/10` | RSS ingest |
| `news-materialize` | `:02, :17, :32, :47` | T−2 min: summarize + TTS + Redis pin |
| `news-enqueue` | `:00, :15, :30, :45` | NEWS_PAIR fan-out via injector |
| `news-play-count-reset` | `0 0 * * *` | Reset PG + Redis play windows |

Redis pin key: `fm21:news:slot:{city}:{slot_iso}` (TTL ~30m). Enqueue reads pin; 10 min slip skip when backlog too deep.

### 2. RSS ingest dedup (U16)

- URL normalize: lowercase scheme/host, strip `utm_*`, clear fragment.
- **Same text extraction for RSS snippets and HTML fetch** (`extract_article_text`) before `content_hash` — avoids syndication bypass when one copy stays on RSS path and another fetches HTML.
- Skip insert when normalized body `< MIN_BODY_LEN` (30 chars) → `SKIPPED_EMPTY_BODY`.
- Per-entry try/except in fetch loop — one DB error must not abort remaining feed entries.

**Live fetch:** Habr/3DNews may need Russian CA bundle in `news-fetch` image or relaxed `verify=False` in dev only.

### 3. Summarize + TTS idempotency (U17–U18)

- Summarizer re-fetches article from `source_url` (body not stored in PG).
- GigaChat: official SDK, 150–250 RU words, one retry → `failed`.
- SaluteSpeech: OAuth 30 min cache; `text:synthesize` wav16 → ffmpeg MP3.
- TTS Redis cache: `fm21:tts:cache:{sha256(summary_ru)}` — AE3 repeat uses cached file, no second synthesis.

### 4. Play count (U19, ADR-007)

- PG `play_count` source of truth; increment **once per slot** after all cities accept enqueue (U21).
- Redis mirror `fm21:news:played:{content_hash}` TTL 86400 for fast selection skip.
- Selection skips items at cap when alternatives exist; fallback to oldest-played ready item (cached `audio_url`).

### 5. NEWS_PAIR on air (U21–U22)

Injector payload per `broadcast-semantics.md`:

```json
{
  "type": "NEWS_PAIR",
  "priority": 80,
  "uri": "file:///data/news/{id}.mp3",
  "meta": { "stinger_uri": "file:///data/news/news-stinger.mp3", "title": "...", "duration_sec": 90 }
}
```

Liquidsoap `dequeue.lua`: atomic stinger then news in one dequeue; AD enqueued mid-pair waits (AE2).

### 6. Metadata + bot (U23)

- `NEWS_PAIR` → `content_type: news` in metadata service.
- `/status` reports `next_news_at` from UTC slot clock (replaces stub).

## Verification

```bash
docker compose run --rm test pytest tests/test_news_*.py tests/test_metadata_news.py \
  tests/test_injector.py tests/test_dequeue_priority.py -v
```

Manual smoke (orchestrator):

```bash
docker compose up -d postgres redis db-migrate injector liquidsoap icecast
docker compose run --rm news-fetch python -m services.news.workers.fetch_cron --once
# materialize + enqueue: --once on respective workers at slot boundary, or wait for UTC :02/:15
curl -I http://localhost:8000/moscow
```

## ADRs (Path A, 2026-06-11)

`docs/adr/004-news-sourcing.md` through `010-news-slot-timezone.md` — approved assumptions for closed beta.
