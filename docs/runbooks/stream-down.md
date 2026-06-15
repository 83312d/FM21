# Stream outage runbook (U31)

Use when listeners report dead air, gateway mounts return non-200, or `/api/health` reports `degraded`.

## Quick triage

1. **Public liveness** (via gateway):

   ```bash
   curl -s http://127.0.0.1:8080/api/health
   ```

   Expect `{"status":"ok"}`. `degraded` usually means Redis is unreachable from metadata.

2. **Deep health** (Docker network only — not exposed on the public gateway):

   ```bash
   docker compose exec metadata curl -s http://127.0.0.1:8080/internal/health | jq .
   ```

   Check `components.redis`, `components.postgres`, `components.icecast`, `components.liquidsoap`.

3. **Icecast status**:

   ```bash
   curl -s http://127.0.0.1:8000/status-json.xsl | head
   ```

4. **Mount smoke** (per city):

   ```bash
   curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/moscow
   ```

## Component recovery

| Component | Symptom | Action |
|-----------|---------|--------|
| **Redis** | `components.redis.status` = `down` | `docker compose restart redis`; verify `REDIS_URL` in metadata/injector |
| **Postgres** | `components.postgres.status` = `down` | `docker compose ps postgres`; run `db-migrate` after PG is healthy |
| **Icecast** | `components.icecast.status` = `down` | `docker compose logs icecast`; restart icecast |
| **Liquidsoap** | `components.liquidsoap.status` = `down` | `docker compose logs liquidsoap`; confirm mount `/moscow` returns 200 on Icecast |

Restart broadcast path (dev stack):

```bash
docker compose restart liquidsoap icecast
```

Re-check deep health until all components report `ok`.

## Escalation

- If Redis and Postgres are healthy but Liquidsoap stays `down`, inspect `broadcast/liquidsoap/fm21.liq` dequeue and queue depth (`/api/queue/{city}`).
- If mounts return 200 but audio is silent, verify Liquidsoap is connected as source in Icecast admin (`/admin/` — dev only).

## Related

- Plan unit U31 — `docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md`
- Gateway config — `docker/nginx-gateway.conf` (dev), `deploy/production/gateway/nginx.conf` (prod)
- `/internal/health` is intentionally **not** proxied through nginx; use `docker compose exec metadata` or attach Prometheus to the metadata container network.
