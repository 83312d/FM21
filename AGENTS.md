# FM21 — Agent Guide

Read this file first. Do not re-derive product behavior from `docs/tz.md` (legacy brief; implementation sections are superseded).

## Read-first

| Order | Document | Purpose |
|-------|----------|---------|
| 1 | [STRATEGY.md](STRATEGY.md) | Problem, approach, metrics, delivery tracks |
| 2 | [docs/brainstorms/2026-06-08-fm21-requirements.md](docs/brainstorms/2026-06-08-fm21-requirements.md) | Requirements R1–R39, acceptance examples AE1–AE6 |
| 3 | `docs/contracts/` | Broadcast, listener, operator behavior (**U2**) |
| 4 | `docs/adr/` | ADR-001 delivery, ADR-002 licensing, [ADR-003 containers](docs/adr/003-container-strategy.md) |
| 5 | [docs/plans/2026-06-08-001-feat-fm21-greenfield-plan.md](docs/plans/2026-06-08-001-feat-fm21-greenfield-plan.md) | Implementation units U1–U11, KTD decisions |
| 6 | `spec/acceptance.yaml` | Machine-verifiable acceptance (**U3**) |
| 7 | `docs/solutions/` | Compound learnings after each slice (R29) |

**Implementation authority:** contracts + `spec/acceptance.yaml` + plan KTD table. `docs/tz.md` is context only.

## Container policy (R38, R39, ADR-003)

- **Monorepo** — single repo for broadcast, services, web, docker, deploy, tests.
- **Docker images everywhere** — dev, CI, staging, production. No host `pip install`, `npm install`, or system ffmpeg for project workflows.
- **Compose = dev only** — `docker-compose.yml` orchestrates local stack. Production uses same images from `deploy/` (U11), not root Compose.
- **Do not** document or implement host-native run commands (`python -m pytest`, `npx agent-browser`) as the primary path.

## Delivery model (R28)

Work proceeds in **vertical slices**, not horizontal layers:

| Phase | Units | Outcome |
|-------|-------|---------|
| 0 | U1–U3 | Docs, contracts, acceptance spec |
| 1 | U4–U8 | Geo proof: two mounts, Moscow-only ad, player |
| 2+ | U9–U11 | Music, news, production |

Execute one implementation unit per agent session unless the user expands scope.

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
| U4+ (code) | `/ce-code-review` | `mode:autofix plan:docs/plans/2026-06-08-001-feat-fm21-greenfield-plan.md` |

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
```

Add Dockerfiles under `docker/` and wire services in `docker-compose.yml` per unit. Update this section when new compose services land.

## Repository layout

```text
docker/        Dockerfiles (python base, liquidsoap, gateway, test, e2e)
deploy/        Production manifests — not Compose (U11)
broadcast/     Liquidsoap + Icecast configs
services/      geo, bot, metadata, injector (Python 3.12 in containers)
web/           Listener player (static HTML/JS, served via gateway)
data/          Static music bed, transcoded ads (ads gitignored)
docs/          adr, contracts, plans, solutions
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

- **U1 done:** Strategy, this file, README, `.env.example`, scaffolding ignores
- **U2 done:** ADR-001/002, behavior contracts (`docs/contracts/`)
- **ADR-003 done:** Container strategy (monorepo, images everywhere, Compose dev-only)
- **Next:** U3 — acceptance spec (`spec/acceptance.yaml`) + OpenAPI
