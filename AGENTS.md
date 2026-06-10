# FM21 — Agent Guide

Read this file first. Do not re-derive product behavior from `docs/tz.md` (legacy brief; implementation sections are superseded).

## Read-first

| Order | Document | Purpose |
|-------|----------|---------|
| 1 | [STRATEGY.md](STRATEGY.md) | Problem, approach, metrics, delivery tracks |
| 2 | [docs/brainstorms/2026-06-08-fm21-requirements.md](docs/brainstorms/2026-06-08-fm21-requirements.md) | Requirements R1–R39, acceptance examples AE1–AE6 |
| 3 | `docs/contracts/` | Broadcast, listener, operator behavior (**U2**) |
| 4 | `docs/adr/` | ADR-001 delivery, ADR-002 licensing, [ADR-003 containers](docs/adr/003-container-strategy.md) |
| 5 | [docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md](docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md) | **Canonical plan** — U4–U34, phased delivery |
| 5b | [docs/plans/2026-06-08-001-feat-fm21-greenfield-plan.md](docs/plans/2026-06-08-001-feat-fm21-greenfield-plan.md) | U4–U8 unit detail (supplement to 002) |
| 5c | [docs/brainstorms/2026-06-08-fm21-full-product-requirements.md](docs/brainstorms/2026-06-08-fm21-full-product-requirements.md) | Full-product requirements (TZ v1.1 behavior) |
| 5d | [docs/prompts/orchestrator-phases.md](docs/prompts/orchestrator-phases.md) | Orchestrator + worker prompts per phase |
| 6 | `spec/acceptance.yaml` | Machine-verifiable acceptance (**U3**) |
| 6b | [docs/openapi.yaml](docs/openapi.yaml) | Phase 1 listener HTTP API — geo + metadata (**U3**) |
| 7 | `docs/solutions/` | Compound learnings after each slice (R29) |

**Implementation authority:** contracts + `spec/acceptance.yaml` + plan **002** KTD table. `docs/tz.md` is context only.

## Container policy (R38, R39, ADR-003)

- **Monorepo** — single repo for broadcast, services, web, docker, deploy, tests.
- **Docker images everywhere** — dev, CI, staging, production. No host `pip install`, `npm install`, or system ffmpeg for project workflows.
- **Compose = dev only** — `docker-compose.yml` orchestrates local stack. Production uses same images from `deploy/` (U11), not root Compose.
- **Do not** document or implement host-native run commands (`python -m pytest`, `npx agent-browser`) as the primary path.

## Delivery model (R28)

Work proceeds in **vertical slices**, not horizontal layers:

| Phase | Units | Outcome | Branch (example) |
|-------|-------|---------|------------------|
| 0 | U1–U3 | Docs, contracts, acceptance spec | — |
| 1 | U4–U8 | Geo proof: two mounts, Moscow-only ad, player | `feat/phase-1-foundation` |
| 2 | U9–U14 | Postgres, Yandex music, buffer, priority dequeue, `/order` | `feat/phase-2-music` |
| 3 | U15–U23 | News pipeline, NEWS_PAIR on air | `feat/phase-3-news` |
| 4 | U24–U29 | Full bot, ads service, queue API, multi-city | `feat/phase-4-bot-ops` |
| 5 | U30–U34 | Production deploy, cron, TZ §12 sign-off | `feat/phase-5-production` |

One agent session = one **phase** (orchestrator + subagents) unless the user narrows scope. Prompts: `docs/prompts/orchestrator-phases.md`.

### Inter-session memory (no shared agent RAM)

| Layer | Location | Role |
|-------|----------|------|
| Truth | **git** (`main`, phase branches) | Code + merged docs |
| What to build | `docs/plans/002`, contracts, ADR | Decisions and units |
| How to run a phase | `docs/prompts/orchestrator-phases.md` | Orchestrator/worker prompts |
| How we fixed X | `docs/solutions/` | After `/ce-compound` per slice |
| Secrets | `.env` (never commit) | Tokens, human-only |

New sessions do **not** see prior chats. Subagents only return a summary to the orchestrator. Update **this file `Current status`** after each phase merge.

## Agent Runbook — per unit

**Critical:** `ce-work` does **not** auto-dispatch subagents or auto-invoke review skills. The orchestrator (this session) must **explicitly** call `Task` subagents and load `/ce-code-review` or `/ce-doc-review` before declaring a unit done. Listing steps below is mandatory, not optional.

### Definition of done (every unit)

A unit is **not complete** until all applicable items pass:

- [ ] Implementation matches plan unit `Goal`, `Files`, `Verification`
- [ ] Tests or doc verification (see table below)
- [ ] Review skill invoked and findings addressed (no skip)
- [ ] `ce-compound` if non-trivial learnings (R29)
- [ ] User explicitly requested commit (if committing)

### Execution steps

```
1. ce-work scope  — read plan unit only; create Task list with U-ID prefix
2. implement      — inline OR subagents (see dispatch table)
3. verify         — tests (Docker) or doc checklist
4. review         — MANDATORY separate skill invocation (not inline self-review)
5. ce-compound    — docs/solutions/ when warranted
6. commit         — only when user asks
```

### Subagent dispatch (orchestrator chooses)

| Unit type | Default strategy | When to parallelize |
|-----------|------------------|---------------------|
| **Docs** (U1–U3) | **Parallel:** 1 subagent per file group — ADRs (`docs/adr/`), contracts (`docs/contracts/`), spec (`spec/` + OpenAPI) | U2: dispatch 2 agents (ADRs batch + contracts batch) in parallel |
| **Code** (U4+) | **Serial** unless plan `Files:` lists have zero intersection | U4 ∥ U6 after U2: separate worktrees (`ce-worktree`) |
| **Trivial** (typo, one file) | Inline OK | Never |

`ce-work` defaults to **inline** unless the prompt says `use subagents` or the table above applies. For FM21, **docs and code units use subagents by default.**

### Review gate (MANDATORY — separate skill, not self-review)

| Unit | Review skill | Arguments |
|------|--------------|-----------|
| U1–U3 (markdown) | `/ce-doc-review` | requirements: `docs/brainstorms/2026-06-08-fm21-requirements.md`, plan unit id |
| U4+ (code) | `/ce-code-review` | `mode:autofix plan:docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md` |

After review: fix P0/P1 in scope; document accepted residuals in session summary.

### Doc units (U1–U3) verification without pytest

- All internal markdown links resolve
- Contracts answer plan flow gaps Q1–Q7 (U2 `Verification`)
- ADR-001/002 consistent with `docs/brainstorms/...-requirements.md` Key Decisions
- **Still run `/ce-doc-review`** — link check alone is not a substitute

### Code units (U4+)

Run tests via Docker (see Commands). Do not skip tests when the plan unit defines them.

## Commands

```bash
# Dev stack (U4+) — Compose is development-only
docker compose up

# Unit / integration tests (U5+) — run inside test image
docker compose run --rm test pytest tests/
docker compose run --rm test pytest tests/test_injector.py -v

# E2E player (U7+)
docker compose run --rm e2e

# Smoke: ICY mount headers
curl -I http://localhost:8000/moscow

# Phase 2+ (Postgres, music)
docker compose run --rm test pytest tests/test_db_schema.py tests/test_yandex_provider.py tests/test_playlist_rules.py tests/test_buffer_worker.py -v
```

Add Dockerfiles under `docker/` and wire services in `docker-compose.yml` per unit. Update this section when new compose services land.

## Repository layout

```text
docker/        Dockerfiles (python base, liquidsoap, gateway, test, e2e)
deploy/        Production manifests — not Compose (U11)
broadcast/     Liquidsoap + Icecast configs
services/      geo, bot, metadata, injector, db, music (Python 3.12 in containers)
web/           Listener player (static HTML/JS, served via gateway)
data/          Static music bed, transcoded ads (ads gitignored)
docs/          adr, contracts, plans, prompts, solutions
spec/          acceptance.yaml
tests/         pytest + agent-browser e2e
```

## Agent constraints (R30, R31)

- **No live runtime mutation:** Agents do not LPUSH to production Redis, restart Liquidsoap in prod, or edit live queue state. Enqueue happens only through deployed services or documented dev workflows after U4.
- **Playlist policy seam:** Music selection rules live in `services/music/playlist_rules.yaml` (Phase 2). Do not embed playlist logic in Liquidsoap or injector core.
- **Human-only:** `docs/adr/*` (human approves architecture), `.env` / secrets, production `broadcast/liquidsoap/cities.yaml` city list.

## Human vs agent

| Human | Agent |
|-------|-------|
| Approve ADRs, secrets, production city list | Implement units per plan |
| Provide Telegram token, GeoIP DB, OAuth tokens | Write Dockerfiles, compose services, tests |
| Run stakeholder demos | `ce-compound` after each slice |

## Current status

**Branch:** `feat/phase-2-music` (Phase 2 in progress; Phase 1 merged to `main` via PR #4).

| Phase | Status | Notes |
|-------|--------|-------|
| 0 U1–U3 | ✅ on `main` | Docs, contracts, acceptance, OpenAPI |
| 1 U4–U8 | ✅ merged | Compose stack, geo, player, injector, bot voice ads |
| 2 U9–U14 | 🔄 in progress | See unit row below |
| 3–5 | ⏳ | Per plan 002 |

**Phase 2 unit tracker** (update when units land; verify on branch tip):

| Unit | Status | Verification hint |
|------|--------|-------------------|
| U9 Postgres | 🔄 | `services/db/`, `test_db_schema.py`, compose `postgres` + `db-migrate` |
| U10 Yandex provider | 🔄 | `services/music/yandex_provider.py`, `test_yandex_provider.py` |
| U11 Playlist rules | 🔄 | `playlist_rules.yaml`, `test_playlist_rules.py` |
| U12 Music buffer | 🔄 | `music-worker` service, `test_buffer_worker.py` |
| U13 Priority dequeue | ⏳ | Liquidsoap still `RPOP` — needs LRANGE+LREM / priority |
| U14 Bot `/order` | ⏳ | `CommandHandler("order", coming_soon)` stub remains |

**Phase 2 env:** `YANDEX_MUSIC_OAUTH_TOKEN` in `.env`; `MUSIC_PROVIDER=yandex` for live API (default `static` in compose). ADR-002 closed beta only.

**Planning docs on `main`:** plan 002, full-product requirements, `docs/prompts/orchestrator-phases.md` (PR #3).

**Solutions backlog:** add `/ce-compound` entries for Phase 1 and Phase 2 when slices close (`docs/solutions/` — only U3 doc exists today).
