# ADR-004: News sourcing & attribution

**Status:** Accepted (Path A assumptions, 2026-06-11)  
**Date:** 2026-06-11  
**Deciders:** Product owner  
**Requirements:** R18, R34

## Context

Phase 3 ingests IT news via RSS for radio summarization and on-air slots. Feed selection affects content quality, legal attribution, and operational burden.

## Decision

### 1. Human-maintained source registry

- Sources live in `services/news/sources.yaml` — per-source `id`, `name`, `url`, `enabled`, `weight`.
- Production and dev lists require explicit human approval before `enabled: true` fetch runs.

### 2. Approved closed-beta feed list

| id | Source | URL |
|----|--------|-----|
| `habr` | Habr — все статьи | `https://habr.com/ru/rss/articles/?fl=ru` |
| `3dnews` | 3DNews — новости | `https://3dnews.ru/news/rss/` |

Both sources: `enabled: true`, `weight: 1`. Approved 2026-06-11.

### 3. Tier 1 RSS only — no search fallback

- Phase 3 uses **RSS ingest only** from the registry.
- Tier 2/3 web search or aggregator fallback is **out of scope** until a future ADR amendment.

### 4. Dedup and attribution

- URL normalize (strip `utm_*` query params) before insert; `UNIQUE(source_url)`.
- `content_hash` for syndicated duplicate bodies; `UNIQUE(content_hash)` when present.
- On-air copy is LLM-summarized Russian radio script (ADR-009); source URL stored in DB for audit, not read on air.

## Consequences

- Adding feeds requires editing `sources.yaml` + human approval.
- No automatic discovery of new sources.
- English-language tier-1 feeds (HN, TechCrunch, etc.) deferred — Habr + 3DNews provide Russian IT coverage for closed beta.
