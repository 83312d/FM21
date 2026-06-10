# ADR-002: Music licensing — closed beta vs production

**Status:** Accepted  
**Date:** 2026-06-08  
**Deciders:** Product owner  
**Requirements:** R10, R19, R33, R35

## Context

FM21 fills airtime with music between ads, news, and bot orders. The legacy brief assumes Yandex Music via an unofficial API and personal subscription token. Yandex Music has **no official commercial re-streaming API**; using a personal OAuth token for public internet radio violates typical ToS and does not grant performance rights for broadcast.

We need a licensing path that:

- Unblocks Phase 1 geo proof without Yandex complexity.
- Allows friends-only closed beta with acceptable risk disclosure.
- Defines a production trajectory before public launch.

## Decision

### 1. Phase 1 — static royalty-free catalog

Geo vertical slice (U4–U8) uses loopable MP3 files on disk (`data/music/static/`). No external music API. This proves broadcast and geotargeting without licensing risk.

### 2. Phase 2 closed beta — Yandex Music via personal OAuth

- Implement a `MusicProvider` interface; Yandex is one adapter, not core broadcast logic (R31).
- OAuth token stored in secrets (`.env` / deploy secrets); never exposed to the browser.
- Stream URLs re-resolved at dequeue time (URLs expire). The music buffer worker (U9) rewrites `uri` immediately before LPUSH or via a pre-play hook — Liquidsoap plays the resolved URI; it does not call Yandex directly.
- **Scope limit:** closed beta / friends-only listeners. Operators accept ToS and licensing risk explicitly.
- Bot `/order` searches Yandex catalog and enqueues `MUSIC_ORDER` for operator's `city_tag`.

### 3. Production / public launch — separate license required

Public FM21 cannot ship on personal Yandex OAuth alone. Before public launch, product owner must choose and fund one of:

| Path | Notes |
|------|-------|
| **Licensed B2B provider** (e.g. Feed.fm, similar) | Commercial internet radio rights; quote-based |
| **Self-hosted licensed library** | Owned or licensed catalog on disk/S3 |
| **Royalty-free / CC catalog at scale** | Lower product quality; legally clear |

ADR-002 does not pre-select the production vendor — it **blocks** public launch until a path is chosen and documented in an ADR amendment or ADR-004.

### 4. Royalty-free fallback

If Yandex integration breaks (API change, token revocation, rate limits), the system falls back to static or royalty-free catalog without changing Liquidsoap queue semantics. Playlist selection rules live in `services/music/playlist_rules.yaml` — not in broadcast core.

### 5. Playlist policy seam (R31)

Developers and admins change music **selection** via `playlist_rules.yaml` and `/playlist` (admin). Broadcast Semantics (priorities, no-interrupt, block types) remain unchanged when playlists change.

## Consequences

### Positive

- Phase 1 ships without OAuth or Yandex proxy.
- `MusicProvider` abstraction limits blast radius of API changes.
- Clear human gate before public commercial use.

### Negative

- Closed beta music quality depends on personal subscription — not representative of production.
- Production licensing may add recurring cost and integration work (U9, Phase 4).

## Implementation notes

| Phase | Music source | `MUSIC` filler | `MUSIC_ORDER` |
|-------|--------------|----------------|---------------|
| 1 | `data/music/static/` | Liquidsoap / music worker | Not available (bot stubs) |
| 2 | Yandex via `MusicProvider` | Yandex playlists per rules | Bot `/order` |
| Production | TBD licensed path | Licensed catalog | Licensed search |

## Implementation appendix (U10)

| Component | Location | Notes |
|-----------|----------|-------|
| `MusicProvider` ABC | `services/music/provider.py` | `search`, `get_playlist_tracks`, `resolve_stream_url` |
| Factory | `get_music_provider()` / `create_music_provider()` | `MUSIC_PROVIDER=yandex\|static`; invalid/missing Yandex token → `StaticProvider` |
| Yandex adapter | `services/music/yandex_provider.py` | OAuth via `YANDEX_MUSIC_OAUTH_TOKEN` only; never logged |
| Static fallback | `services/music/static_provider.py` | Reads `STATIC_MUSIC_DIR` (`data/music/static/` in dev) |
| Stream URL cache | `tracks_cache` table | Re-resolve when expiry is within 2 minutes |
| Playlist ID format | `{uid}:{kind}` | Yandex user playlist reference for `get_playlist_tracks` |

Buffer worker (U12) and playlist rules (U11) consume this interface; Liquidsoap never calls Yandex directly.

## Related

- [ADR-001](001-delivery-model.md) — `MUSIC` and `MUSIC_ORDER` queue types
- [Broadcast Semantics](../contracts/broadcast-semantics.md) — priority table
- [Operator Contract](../contracts/operator-contract.md) — `/order` behavior (Phase 2)
- Requirements brainstorm Q1 (Yandex OAuth for beta; production needs separate license)
