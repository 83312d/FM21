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

After the user assigns a unit (e.g. `/ce-work docs/plans/...` + unit id):

```
1. ce-work     — implement only the requested unit; respect Scope Boundaries in the plan
2. tests       — run via Docker (see Commands); never require host toolchains
3. ce-code-review mode:autofix — fix findings in scope
4. ce-compound — if non-trivial learnings, write docs/solutions/<topic>.md (R29)
5. commit      — conventional message; user must request commit explicitly
```

Do not skip tests for units that define them. Documentation-only units (U1–U3) verify links and reviewer checklist instead.

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
- **ADR-003 done:** Container strategy (monorepo, images everywhere, Compose dev-only)
- **Next:** U2 — ADR-001/002 + behavior contracts (`docs/contracts/`)
