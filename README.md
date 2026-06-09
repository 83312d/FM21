# FM21

Geotargeted internet radio: one synchronous live stream per city (Moscow, Saint Petersburg, …), continuous music and news, city-targeted voice ads from Telegram. Listeners use an open web player; no account required.

**Stack (Phase 1):** Liquidsoap + Icecast broadcast spine, Redis enqueue bus, Python glue services, static HTML player with ICY playback. **Monorepo; all services run in Docker** (ADR-003).

## Prerequisites

**Host:** Docker Engine + Docker Compose v2 only. No local Python, Node, ffmpeg, or Liquidsoap installs.

Optional: browser for player; ngrok/Cloudflare tunnel for Telegram webhook in dev.

## Quickstart

1. Read [AGENTS.md](AGENTS.md) — agent onboarding and unit workflow.
2. Copy `.env.example` to `.env` and fill secrets (human-only). Optional: set `ICECAST_SOURCE_PASSWORD` (default `fm21dev`, must match `broadcast/icecast/icecast.xml`).
3. Start the dev broadcast stack:
   ```bash
   docker compose build
   docker compose up -d
   ```
   Icecast mounts: `http://localhost:8000/moscow` and `http://localhost:8000/spb`. Smoke check:
   ```bash
   curl -I http://localhost:8000/moscow
   ```
   Gateway player (U7) will be at `http://localhost:8080`.

4. Tests (pytest from U5+; e2e from U7):
   ```bash
   docker compose run --rm test
   docker compose run --rm e2e
   ```

`docker-compose.yml` is **development only**. Staging and production use the same images via `deploy/` (U11), not root Compose.

Product requirements: [docs/brainstorms/2026-06-08-fm21-requirements.md](docs/brainstorms/2026-06-08-fm21-requirements.md).  
Container strategy: [docs/adr/003-container-strategy.md](docs/adr/003-container-strategy.md).  
Implementation plan: [docs/plans/2026-06-08-001-feat-fm21-greenfield-plan.md](docs/plans/2026-06-08-001-feat-fm21-greenfield-plan.md).

Legacy brief (`docs/tz.md`) is not the implementation source — use contracts and the plan instead.
