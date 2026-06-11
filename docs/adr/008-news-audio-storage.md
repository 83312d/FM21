# ADR-008: News audio storage — dev vs prod

**Status:** Accepted (Path A assumptions, 2026-06-11)  
**Date:** 2026-06-11  
**Deciders:** Product owner  
**Requirements:** R20, R38

## Context

Voiced news MP3s and the stinger asset must be readable by Liquidsoap inside broadcast containers. Dev uses Compose; prod uses deploy manifests (ADR-003).

## Decision

### 1. Development (Compose)

- Local volume mounted at `/data/news/` in news workers, injector path, and Liquidsoap.
- Audio URI pattern: `file:///data/news/{id}.mp3`.
- Stinger: `file:///data/news/news-stinger.mp3` (committed 3–5s asset in `data/news/`).
- `docker-compose.yml` wires shared volume across `news-*` services and `liquidsoap`.

### 2. Production (U30 cutover)

- **Default assumption:** same `file://` layout on shared VM disk until S3 path is chosen.
- Optional S3 adapter in `services/news/storage/s3.py` — not required for Phase 3 exit.
- Prod bucket, credentials, and URI scheme documented in `deploy/README.md` at U30.

### 3. Storage interface

- `services/news/storage/local.py` for dev; factory selects backend via env (`NEWS_STORAGE=local|s3`).
- TTS worker writes file, sets `news_items.audio_url`, probes duration.

## Consequences

- Compose stack self-contained without cloud storage for Phase 3.
- Multi-node prod may require S3 amendment before horizontal scale.
