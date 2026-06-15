# FM21 production deploy

Production manifests live under `deploy/production/` (U30+). **Local development** uses root `docker-compose.yml` (ADR-003) — do not use the prod compose file for day-to-day dev.

System overview (all services, diagrams): [docs/architecture.md](../docs/architecture.md).

## Local-only production quickstart (pet project)

This stack runs on a single machine with Docker. Gateway listens on **HTTP** at `127.0.0.1:8080` (no TLS). Telegram bot defaults to **long polling** (`BOT_MODE=polling`) so no public HTTPS or ngrok is required.

```bash
# From repo root — never commit .env
cp deploy/production/env.template .env
# Edit .env: set TELEGRAM_BOT_TOKEN, POSTGRES_PASSWORD, ICECAST_SOURCE_PASSWORD,
# INTERNAL_ENQUEUE_TOKEN, TELEGRAM_WEBHOOK_SECRET, and other secrets.

docker compose -f deploy/production/docker-compose.prod.yml up -d --build
```

Smoke checklist:

```bash
curl -sf http://127.0.0.1:8080/api/health
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/moscow
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/spb
curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/ekb
```

Optional: seed GeoIP DB and static music into the `fm21_data` volume before first listen (copy `GeoLite2-City.mmdb` and `data/music/static/` into the volume mount path).

### Telegram: polling vs webhook

| Mode | When | Config |
|------|------|--------|
| **polling** (default) | Local pet project | `BOT_MODE=polling` — bot pulls updates from Telegram API |
| **webhook** | Public HTTPS endpoint | `BOT_MODE=webhook`, `TELEGRAM_WEBHOOK_URL=https://host` (no path suffix) |

Webhook registration (HTTPS only — Telegram rejects HTTP):

```bash
# After gateway is reachable via HTTPS (ngrok, Caddy, cloud LB):
export TELEGRAM_WEBHOOK_URL=https://your-host.example.com
bash scripts/set_telegram_webhook.sh
```

Verify: `curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"`

### Optional future: ngrok for webhook testing

1. Start prod stack (`docker compose -f deploy/production/docker-compose.prod.yml up -d`).
2. Tunnel gateway: `ngrok http 8080` → copy the `https://….ngrok-free.app` URL.
3. Set `TELEGRAM_WEBHOOK_URL` to that HTTPS base (no `/api/bot/webhook` suffix).
4. Set `BOT_MODE=webhook`, restart bot, run `scripts/set_telegram_webhook.sh`.

TLS/nginx SSL termination in `deploy/production/gateway/nginx.conf` is **not** configured for the pet project — add a reverse proxy or extend nginx when moving beyond localhost.

### Gateway rate limits (U33)

Production nginx applies `limit_req` per client IP on:

| Path | Zone | Rate | Burst |
|------|------|------|-------|
| `/api/geo/*` | `geo_api` | 10 req/s | 20 |
| `/api/bot/webhook` | `bot_webhook` | 5 req/s | 10 |

Exceeded requests return **HTTP 429**. The web player uses same-origin `fetch` — CORS headers are not required. Static assets (`*.js`, `*.css`, images, fonts) get `Cache-Control: public, immutable` with 7-day `expires`.

**Manual load test** (with prod stack up and gateway rebuilt):

```bash
# Expect mostly 200, then 429 once burst + steady rate are exhausted:
for i in $(seq 1 40); do
  curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/api/geo/detect
done | sort | uniq -c
```

Automated contract: `pytest tests/test_gateway_rate_limit.py`.

## Rollback procedure

1. Stop the current stack without removing volumes (preserves Postgres + `fm21_data`):

   ```bash
   docker compose -f deploy/production/docker-compose.prod.yml down
   ```

2. Check out the previous known-good git tag or commit on this branch.

3. Rebuild and start:

   ```bash
   docker compose -f deploy/production/docker-compose.prod.yml up -d --build
   ```

4. Re-run the smoke checklist above. If bot used webhook mode, re-run `scripts/set_telegram_webhook.sh`.

5. If schema migration failed, restore Postgres from backup (`pgdata` volume) before restarting.

**Nuclear rollback** (data loss): `docker compose -f deploy/production/docker-compose.prod.yml down -v` then redeploy from template `.env`.

## Adding a city

Active cities are defined in `broadcast/liquidsoap/cities.yaml`. Each entry becomes:

- an Icecast mount `/{tag}` (listener stream),
- a Redis queue `fm21:queue:{tag}`,
- a Liquidsoap output pipeline (spawned automatically from the YAML list),
- geo/bot/injector/metadata validation (no Python code changes when fields below are complete).

### 1. Edit `broadcast/liquidsoap/cities.yaml`

Add a block under `cities:`:

```yaml
  - tag: ekb
    name: Yekaterinburg
    display_name: Екатеринбург
    lat: 56.8389
    lon: 60.6057
    aliases:
      - yekaterinburg
      - екатеринбург
```

| Field | Required | Purpose |
|-------|----------|---------|
| `tag` | yes | URL slug, Redis key suffix, operator `/city` argument |
| `name` | yes | English label (logs, Icecast) |
| `display_name` | recommended | Listener badge / bot messages |
| `lat`, `lon` | recommended | Reverse geocode nearest-city |
| `aliases` | optional | GeoIP city-name matching |

### 2. Add Icecast mount

In `broadcast/icecast/icecast.xml`, duplicate a `<mount>` block and set `mount-name`, `stream-name`, and `stream-url` for the new tag.

Liquidsoap (`broadcast/liquidsoap/fm21.liq`) reads `cities.yaml` at runtime — **no script edit** is required.

### 3. Add gateway route

**Dev Compose** — `docker/nginx-gateway.conf`:

```nginx
    location = /ekb {
        proxy_pass http://icecast:8000/ekb;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_set_header Host $host;
        proxy_set_header Connection "";
    }
```

**Production** — mirror in `deploy/production/gateway/nginx.conf`, then rebuild gateway image.

### 4. Restart broadcast stack

Dev:

```bash
docker compose up -d --build icecast liquidsoap gateway
```

Production:

```bash
docker compose -f deploy/production/docker-compose.prod.yml up -d --build icecast liquidsoap gateway
```

Verify mounts:

```bash
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:8080/moscow
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:8080/spb
curl -sf -o /dev/null -w "%{http_code}\n" http://localhost:8080/ekb
```

### 5. Smoke isolation

Enqueue an AD for the new city only; confirm other city queues stay empty:

```bash
# via injector internal API or Telegram voice ad with city keyboard
```

`pytest tests/test_multi_city.py` encodes the expected isolation contract.

### Checklist

- [ ] `cities.yaml` entry with geo fields
- [ ] Icecast `<mount>` block
- [ ] Gateway `location = /{tag}` proxy (dev + prod nginx)
- [ ] Stack restarted; all mounts return HTTP 200
- [ ] City-scoped AD does not appear in other `fm21:queue:*` keys
