# ADR-003: Container strategy — Docker everywhere, Compose for dev only

**Status:** Accepted  
**Date:** 2026-06-08  
**Deciders:** Product owner  
**Requirements:** R38, R39

## Context

FM21 is a monorepo with heterogeneous runtimes: Liquidsoap, Icecast, Redis, Python glue services (FastAPI, Telegram bot, ffmpeg), static web player, and test runners (pytest, agent-browser). Developers and CI must not depend on host-installed Python, Node, ffmpeg, or Liquidsoap — only Docker.

Staging and production must run the same container images built from this repository, not ad-hoc host installs.

## Decision

1. **Monorepo.** One repository holds `broadcast/`, `services/`, `web/`, `docker/`, `tests/`, and deployment manifests. No split repos for Phase 1.

2. **Every component ships as a Docker image.** Broadcast spine, each glue service, web static assets (served via nginx or gateway container), and test runners (`test`, `e2e`) have Dockerfiles under `docker/`. Images are the unit of build and deploy in all environments.

3. **Docker Compose is development-only.** `docker-compose.yml` at repo root orchestrates the full local stack (`docker compose up`). It is not used for staging or production.

4. **Non-dev environments** use the same images with environment-specific config (env vars, secrets, volume mounts). Orchestration format (plain `docker run`, Compose on a single VM, Kubernetes, etc.) is chosen in Phase 4 (U11); the invariant is **images in, Compose out**.

5. **Host prerequisites:** Docker Engine + Docker Compose v2. Optional: ngrok/Cloudflare tunnel for Telegram webhook in dev. Browser on host for manual player checks. No `pip install`, `npm install`, or system ffmpeg on the host for project workflows.

## Consequences

### Positive

- Reproducible dev, CI, and production artifacts from one build pipeline.
- Agents run tests via `docker compose run --rm test …` — no local toolchain drift.
- ffmpeg, Liquidsoap, and Python versions pinned in images.

### Negative

- Slower first-time feedback loop vs bare-metal Python during early spikes (mitigated by compose watch/volumes in dev).
- Production orchestrator choice deferred — images must stay orchestrator-agnostic.

## Implementation notes

| Environment | Orchestration | Config |
|-------------|---------------|--------|
| **Development** | `docker-compose.yml` | `.env`, bind mounts for `data/` |
| **CI** | `docker compose run --rm test` / `e2e` | CI env vars, no `.env` file |
| **Staging / Production** | TBD in U11 (`deploy/`) | Secrets manager, managed volumes |

U4 introduces compose skeleton + broadcast images. U5–U8 add one compose service (+ Dockerfile) per glue component. U7 adds `gateway` (or `web`) for static player + API reverse proxy.

## Related

- KTD-6, KTD-11, KTD-12 in implementation plan
- ADR-001 (delivery model) — broadcast processes run inside containers, not as host daemons
