# FM21 production deploy

Production manifests live under `deploy/production/` (U30+). This document covers **operational tasks** that apply to every environment.

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

### 3. Add gateway route (dev Compose)

In `docker/nginx-gateway.conf`, add a static location (do **not** use `$request_uri` in `proxy_pass`):

```nginx
    location = /ekb {
        proxy_pass http://icecast:8000/ekb;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_set_header Host $host;
        proxy_set_header Connection "";
    }
```

Production gateway: mirror the same pattern in `deploy/production/gateway/nginx.conf` (U30).

### 4. Restart broadcast stack

```bash
docker compose up -d --build icecast liquidsoap gateway
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
- [ ] Gateway `location = /{tag}` proxy
- [ ] Stack restarted; all mounts return HTTP 200
- [ ] City-scoped AD does not appear in other `fm21:queue:*` keys
