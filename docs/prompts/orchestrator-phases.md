# FM21 — Orchestrator & Worker Prompts

Промпты для **оркестратора** (одна сессия = одна фаза = одна git-ветка). Оркестратор **не пишет код сам** — спавнит `Task` subagents по юнитам, гоняет verify/review/compound.

**Планы:**
- Полный продукт: `docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md`
- Детали U4–U8: `docs/plans/2026-06-08-001-feat-fm21-greenfield-plan.md` (секции юнитов)
- Требования: `docs/brainstorms/2026-06-08-fm21-full-product-requirements.md`

**Авторитет поведения:** `docs/contracts/` + `spec/acceptance.yaml` + ADR. `docs/tz.md` — только контекст.

---

## Как пользоваться

1. Создай ветку `feat/phase-N-<short-name>` (см. таблицу ниже).
2. Новая Agent-сессия → вставь **Orchestrator prompt** для фазы.
3. Оркестратор для каждого U: `Task` worker → verify → `/ce-code-review` → `/ce-compound` при необходимости.
4. Коммит **только** когда ты явно попросишь.
5. После фазы — демо по **Phase exit criteria**, merge в main по своему процессу.

| Phase | Ветка (пример) | Юниты | Статус |
|-------|----------------|-------|--------|
| 0 | `feat/phase-0-docs` | U1–U3 | ✅ done |
| 1 | `feat/phase-1-foundation` | U4–U8 | next |
| 2 | `feat/phase-2-music` | U9–U14 | |
| 3 | `feat/phase-3-news` | U15–U23 | human: ADR-004+ до U16 |
| 4 | `feat/phase-4-bot-ops` | U24–U29 | |
| 5 | `feat/phase-5-production` | U30–U34 | secrets + staging |

---

## Общие правила оркестратора (во все фазы)

Вставляй этот блок в начало каждого orchestrator prompt (или держи в голове):

```text
ROLE: Orchestrator only. Do NOT implement units inline except one-line fixes after review.

MANDATORY per unit (Definition of done):
1. Read plan unit (Goal, Files, Approach, Test scenarios, Verification) — plan 002; U4–U8 detail in plan 001.
2. Dispatch Task subagent with matching Worker prompt from docs/prompts/orchestrator-phases.md §Workers.
3. Verify via Docker (pytest / e2e / curl) per unit Verification — no host pip/npm.
4. Invoke /ce-code-review mode:autofix plan:docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md — separate skill, not self-review.
5. Fix P0/P1 in scope; /ce-compound → docs/solutions/ if non-trivial learnings.
6. Do NOT commit unless user explicitly asks.
7. Do NOT modify AGENTS.md or agent workflow docs unless user asks.
8. Do NOT LPUSH production Redis or mutate live queue state (R30).

Subagent rules:
- Code units: prefer Task subagents; parallelize only when plan Files: have zero intersection.
- After each unit: short status table (U-ID | pass/fail | tests | review).
- Stop phase and report blockers (missing secrets, ADR not approved) — do not invent product behavior.

Container policy: Docker images everywhere; docker compose = dev only; tests via docker compose run --rm test pytest ...
```

---

## Phase 0 — Docs (U1–U3) ✅

Уже сделано. Ретро-оркестратор (опционально):

```text
ORCHESTRATOR — Phase 0 retrospective review only.

Branch: chore/phase-0-doc-review (or stay on main).

Scope: Verify U1–U3 artifacts — no new features.
- /ce-doc-review requirements: docs/brainstorms/2026-06-08-fm21-full-product-requirements.md
- Link check across docs/adr, docs/contracts, spec/acceptance.yaml, docs/openapi.yaml
- Align acceptance.yaml deferred flags with plan 002 phases

Do NOT implement U4+. Report gaps only; fix P0 doc inconsistencies if user approves.
```

---

## Phase 1 — Foundation (U4–U8)

**Exit criteria:** `docker compose up` → ICY on moscow+spb; AE1 geo ad isolation; AE4 badge; AE6 background audio; voice ad via Telegram.

```text
ORCHESTRATOR — FM21 Phase 1 (U4–U8).

Git branch: feat/phase-1-foundation (create/checkout first).

Plan: docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md Phase 1
Detail: docs/plans/2026-06-08-001-feat-fm21-greenfield-plan.md sections U4–U8

Execute units IN ORDER with dependencies; parallelize subagents only as noted:

| Step | Unit | Parallel subagents allowed |
|------|------|----------------------------|
| 1 | U4 | YES — Agent A: docker-compose + Dockerfiles; Agent B: broadcast/liquidsoap + icecast configs |
| 2 | U5 | serial (needs U4 Redis) |
| 3 | U6 | MAY parallel with U5 (no file overlap with injector) |
| 4 | U7 | serial (needs U4 streams + U6 geo) |
| 5 | U8 | serial (needs U5 injector) |

Phase 1 scope limits:
- Static music bed only (no Yandex, no news, no MUSIC_ORDER)
- Bot stubs: /order, /status, /playlist → "coming soon"
- Injector accepts AD type only in Phase 1 (reject MUSIC until Phase 2 unless plan says otherwise)

After ALL units:
- Run: docker compose up; curl -I localhost:8000/moscow; docker compose run --rm test pytest; docker compose run --rm e2e
- Phase integration smoke: two browser tabs moscow vs spb + one Moscow voice ad (AE1)
- /ce-code-review on full phase diff (autofix mode)
- Summarize phase exit criteria pass/fail table

Do NOT start U9+. Do NOT commit unless user asks.
```

---

## Phase 2 — Music (U9–U14)

**Exit criteria:** Yandex tracks in queue; ≥10 MUSIC buffer/city; priority dequeue AD>MUSIC_ORDER>MUSIC; /order works; playlist_rules.yaml seam.

**Human gate before start:** `YANDEX_MUSIC_TOKEN` in `.env`; ADR-002 understood (closed beta only).

```text
ORCHESTRATOR — FM21 Phase 2 (U9–U14).

Git branch: feat/phase-2-music

Plan: docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md units U9–U14

Execution order:
| Step | Unit | Notes |
|------|------|-------|
| 1 | U9 | PostgreSQL — blocks all Phase 2 |
| 2 | U10 | Yandex MusicProvider — needs U9 |
| 3 | U11 | playlist_rules.yaml — needs U9, U10 |
| 4 | U12 | music buffer worker — needs U5, U10, U11 |
| 5 | U13 | Liquidsoap priority dequeue — needs U12; upgrades U4 liq |
| 6 | U14 | bot /order — needs U10–U13, U8 bot skeleton |

Parallelization:
- U10 and U11: SERIAL (U11 depends on provider types)
- Within U9: optional split — migrations vs compose postgres service

Expand injector to accept MUSIC, MUSIC_ORDER (not NEWS_PAIR until Phase 3).

After each unit: pytest in Docker per Verification.

Phase exit integration:
- docker compose up; verify ≥10 MUSIC items in redis per city
- Manual /order → track airs on operator city mount only
- Static fallback when YANDEX_MUSIC_TOKEN invalid (ADR-002)

After U14: phase-level /ce-code-review; compound learnings (Yandex URL expiry, dequeue).

Do NOT start U15 (news). Do NOT commit unless user asks.
```

---

## Phase 3 — News (U15–U23)

**Exit criteria:** News every 15 min; stinger+news atomic; AE2/AE3; play_count ≤3/24h; TZ §12 news rows.

**Human gates before U16:**
- ADR-004 approved (news sourcing)
- ADR-006 (TTS), ADR-009 (LLM) — or explicit assumptions documented
- `GIGACHAT_CREDENTIALS` (and optional `GIGACHAT_SCOPE`), `NEUROZVUK_API_KEY` in `.env`
- Human approves `services/news/sources.yaml` feed list

```text
ORCHESTRATOR — FM21 Phase 3 (U15–U23).

Git branch: feat/phase-3-news

Plan: docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md units U15–U23

STOP at start if ADR-004 not merged or sources.yaml empty — report to user.

Execution order (strict chain):
U15 → U16 → U17 → U18 → U19 → U20 → U21 → U22 → U23

Parallelization (only where safe):
- After U16: U17 (summarizer) ∥ U18 (TTS mocks) — different dirs, no shared files
- Do NOT parallelize U21 (enqueue) with U20 (materialize) on same slot logic

Cron services to add in compose (dev):
- fetch */10
- materialize at :02,:17,:32,:47
- enqueue at :00,:15,:30,:45
- play_count_reset midnight

Injector + Liquidsoap must handle NEWS_PAIR (U21, U22).

After U23:
- Undefer AE2, AE3 in spec/acceptance.yaml
- Manual: hear stinger→news on schedule; submit voice ad during news → no interrupt (AE2)
- docker compose run --rm test pytest tests/test_news_*.py tests/test_injector.py

Phase /ce-code-review on full news pipeline diff.

Do NOT start U24+. Do NOT commit unless user asks.
```

---

## Phase 4 — Bot & ops (U24–U29)

**Exit criteria:** Ads service extracted; full bot commands; /api/queue; multi-city from cities.yaml.

```text
ORCHESTRATOR — FM21 Phase 4 (U24–U29).

Git branch: feat/phase-4-bot-ops

Plan: docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md units U24–U29

Note: Refactors Phase 1 U8 voice path → ads service. Keep AE1 passing throughout.

Execution order:
| Step | Unit | Depends |
|------|------|---------|
| 1 | U24 | U9, U5, U8 |
| 2 | U25 | U9, U8 — MAY parallel with U24 if different agents, watch compose.yml |
| 3 | U26 | U24, U25 |
| 4 | U28 | U13, U7 — MAY start after U26 if metadata blocked |
| 5 | U27 | U25, U28, U11 |
| 6 | U29 | U6, U25, U28 |

Parallelization:
- U24 + U25: parallel OK with separate worktrees OR serial if same agent edits docker-compose.yml
- U28 can run parallel to U26 once U13 done

Remove all "coming soon" bot stubs from U8.

Update docs/contracts/operator-contract.md for implemented commands.

Phase exit:
- Full bot flow: voice, /order, /city, /status, /playlist (admin)
- GET /api/queue/{cityTag} returns 5 items
- Add third city in cities.yaml → third mount without code changes (U29)

Phase /ce-code-review; compound (ads service boundary, operator auth).

Do NOT start U30 deploy. Do NOT commit unless user asks.
```

---

## Phase 5 — Production (U30–U34)

**Exit criteria:** Staging HTTPS; Telegram webhook; cron prod; TZ §12 full checklist; monitoring runbook.

**Human gates:** staging domain, TLS certs, production secrets, production `cities.yaml`.

```text
ORCHESTRATOR — FM21 Phase 5 (U30–U34).

Git branch: feat/phase-5-production

Plan: docs/plans/2026-06-08-002-feat-fm21-full-product-plan.md units U30–U34

Prerequisites: Phases 1–4 merged or complete on this branch.

Execution order:
U30 → U31 → U32 → U33 → U34 (U33 may overlap U30 gateway work — same agent for nginx)

Scope:
- deploy/ manifests ONLY — do NOT use root docker-compose.yml for production
- scripts/set_telegram_webhook.sh
- Public /api/health minimal; /internal/health deep
- Cron container for TZ §9 jobs
- U34: spec/acceptance.yaml full TZ §12 traceability; e2e full-product spec

STOP if user has not provided staging URL + TELEGRAM_WEBHOOK_URL — document required env in deploy/README.md and pause.

Verification:
- Staging smoke checklist (in plan U30)
- getWebhookInfo shows correct URL
- 24h optional soak — document manual step

Final /ce-code-review on entire product diff vs plan 002.

Do NOT commit unless user asks. Do NOT force-push main.
```

---

# Worker prompts (для Task subagents)

Оркестратор копирует промпт юнита в `Task` tool. Каждый worker — **только свой U**, без соседних юнитов.

Шаблон worker (общий хвост для всех):

```text
CONSTRAINTS:
- Implement ONLY this unit. Do not start next unit.
- Read: docs/contracts/, relevant ADR, plan unit section in 002 (U4–U8 detail in 001).
- Docker only for tests. Match existing repo conventions.
- Return: files changed, test commands run + results, manual steps left for orchestrator, blockers.
```

---

## Phase 1 workers

### Worker U4

```text
WORKER U4 — Docker dev stack (Liquidsoap + Icecast + Redis).

Read plan 001 § U4 and plan 002 Phase 1.

Implement:
- docker-compose.yml (icecast, liquidsoap, redis, test/e2e profiles)
- docker/liquidsoap.Dockerfile, icecast.Dockerfile, python.Dockerfile
- broadcast/icecast/icecast.xml, broadcast/liquidsoap/fm21.liq, cities.yaml (moscow, spb)
- data/music/static/ seed 3–5 loop MP3s
- deploy/.gitkeep

Liquidsoap: one ICY mount per city; static bed when Redis empty; 2s crossfade; dead air <5s.
Document Redis consumption approach in broadcast-semantics if spike chooses mechanism.

Verify: docker compose up; curl -I http://localhost:8000/moscow and /spb within 30s.

[CONSTRAINTS block]
```

### Worker U5

```text
WORKER U5 — Queue injector service.

Read plan 001 § U5. Depends on U4 Redis + cities.yaml.

Implement services/injector/*, docker/injector.Dockerfile, tests/test_injector.py, compose service.

POST /internal/enqueue — internal token; Phase 1: AD only (priority 100).
Max 5 pending AD per city (scan queue, not LLEN); city_tag=all fan-out; 409 on 6th.

Verify: docker compose run --rm test pytest tests/test_injector.py -v

[CONSTRAINTS block]
```

### Worker U6

```text
WORKER U6 — Geo API service.

Read plan 001 § U6, docs/openapi.yaml geo paths, listener-contract §3.

Implement services/geo/*, tests/test_geo.py, compose service.

GET /api/geo/detect, GET /api/geo/reverse — map to cities.yaml tags.
GeoIP fallback; missing DB → default city source=default.

Verify: docker compose run --rm test pytest tests/test_geo.py -v

[CONSTRAINTS block]
```

### Worker U7

```text
WORKER U7 — Web player + metadata + gateway.

Read plan 001 § U7, listener-contract, docs/tz.md §6.2 colors only.

Implement web/*, services/metadata/main.py, docker/gateway.Dockerfile, tests/e2e/geo-isolation.spec.ts.

ICY <audio> only — NO Web Audio API, HLS, WebSocket audio.
player.js detection chain; poll now-playing 5s; city switch reconnects live edge.
CSS #44EB99 / #861BE3.

Verify: docker compose run --rm e2e; manual Play button.

[CONSTRAINTS block]
```

### Worker U8

```text
WORKER U8 — Telegram bot voice ads (Phase 1 scope).

Read plan 001 § U8, operator-contract §4.

Implement services/bot/*, docker/bot.Dockerfile, tests/test_transcode.py.

Webhook POST /api/bot/webhook; voice → city inline keyboard → ffmpeg OGG→MP3 EBU R128 → injector AD.
Max 60s. Stub /order, /status, /playlist as "coming soon".

Verify: pytest transcode; document manual AE1 two-tab test for orchestrator.

[CONSTRAINTS block]
```

---

## Phase 2 workers

### Worker U9

```text
WORKER U9 — PostgreSQL full schema (TZ §8.1).

Read plan 002 § U9. Tables: news_items, ads, tracks_cache, playlist_config, broadcast_log.

docker-compose postgres service; services/db/* migrations; tests/test_db_schema.py; DATABASE_URL in .env.example.

Verify: pytest test_db_schema; migration idempotent.

[CONSTRAINTS block]
```

### Worker U10

```text
WORKER U10 — Yandex MusicProvider + static fallback.

Read plan 002 § U10, ADR-002.

services/music/provider.py, yandex_provider.py, static_provider.py, tests with mocked API.

MusicProvider: search, get_playlist_tracks, resolve_stream_url with expiry → tracks_cache.

Verify: pytest; document integration test with real token as optional manual step.

[CONSTRAINTS block]
```

### Worker U11

```text
WORKER U11 — playlist_rules.yaml + rules_loader.

Read plan 002 § U11, R31.

services/music/playlist_rules.yaml, rules_loader.py, rules_schema.py, tests/test_playlist_rules.py.

Boot validation fail-fast on bad YAML. Per-city overrides merge with playlist_config DB.

Verify: pytest test_playlist_rules.

[CONSTRAINTS block]
```

### Worker U12

```text
WORKER U12 — Music buffer worker (≥10 MUSIC per city).

Read plan 002 § U12.

services/music/buffer_worker.py, enqueue.py, docker/music-worker.Dockerfile, tests/test_buffer_worker.py.

Maintain ≥10 MUSIC in fm21:queue:{city}; resolve Yandex URL at enqueue; static fallback on provider failure.

Verify: pytest; redis scan shows ≥10 MUSIC per city in steady state.

[CONSTRAINTS block]
```

### Worker U13

```text
WORKER U13 — Liquidsoap priority dequeue + NEWS_PAIR hook stub.

Read plan 002 § U13, broadcast-semantics §4, ADR-001.

Upgrade broadcast/liquidsoap/fm21.liq + dequeue.lua/sh; tests/test_dequeue_priority.py.

Priority: AD(100) > MUSIC_ORDER(50) > MUSIC(10). NEWS_PAIR: stinger_uri then uri atomically.

Verify: pytest dequeue; manual Yandex track plays between ads.

[CONSTRAINTS block]
```

### Worker U14

```text
WORKER U14 — Bot /order handler.

Read plan 002 § U14, operator-contract.

services/bot/handlers/order.py, parsers, injector_client, tests/test_bot_order.py.

Parse "Title — Artist"; Yandex search; inline confirm; enqueue MUSIC_ORDER priority 50.

Verify: pytest; remove U8 /order stub.

[CONSTRAINTS block]
```

---

## Phase 3 workers

### Worker U15

```text
WORKER U15 — News DB models & repository.

Read plan 002 § U15. Extend news_items with status enum, content_hash, audit fields.

services/news/db/*, migrations, tests/test_news_repository.py.

[CONSTRAINTS block]
```

### Worker U16

```text
WORKER U16 — RSS ingest + sources.yaml.

Read plan 002 § U16, ADR-004 if present.

services/news/sources.yaml (starter feeds), fetcher/*, fetch_cron */10, tests/test_news_fetcher.py.

URL dedup UNIQUE source_url; normalize utm params.

[CONSTRAINTS block]
```

### Worker U17

```text
WORKER U17 — GigaChat summarizer RU 150–250 words.

Read plan 002 § U17, ADR-009 if present.

services/news/summarizer/* (gigachat_client.py), tests/test_news_summarizer.py (mocked GigaChat).

[CONSTRAINTS block]
```

### Worker U18

```text
WORKER U18 — Neurozvuk TTS + storage + stinger.

Read plan 002 § U18, ADR-006/008.

services/news/tts/*, storage/*, data/news/news-stinger.mp3, tests/test_news_tts.py.

Redis TTS cache by summary hash. ffprobe duration.

[CONSTRAINTS block]
```

### Worker U19

```text
WORKER U19 — Selection + play_count + midnight reset.

Read plan 002 § U19, AE3 in spec/acceptance.yaml.

services/news/selection.py, play_count.py, play_count_reset cron, tests.

play_count < 3 per 24h; Redis fm21:news:played:{hash} TTL 86400.

[CONSTRAINTS block]
```

### Worker U20

```text
WORKER U20 — Materialize worker T−2 min.

Read plan 002 § U20.

materialize_cron at :02,:17,:32,:47; pipeline.py; slot pin in Redis; tests/test_news_materialize.py.

[CONSTRAINTS block]
```

### Worker U21

```text
WORKER U21 — News enqueue cron */15 NEWS_PAIR all cities.

Read plan 002 § U21, broadcast-semantics NEWS_PAIR JSON shape.

enqueue_cron; fan-out via injector; 10min slip skip; tests/test_news_enqueue.py.

[CONSTRAINTS block]
```

### Worker U22

```text
WORKER U22 — Liquidsoap NEWS_PAIR hardening + AE2.

Read plan 002 § U22. Atomic stinger+news; AD waits during pair.

Update fm21.liq, test_injector AE2 scenarios, undefer AE2 in acceptance.yaml when ready.

[CONSTRAINTS block]
```

### Worker U23

```text
WORKER U23 — News metadata + AE3 closure.

Read plan 002 § U23.

metadata content_type news; bot /status next_news_at; tests/test_metadata_news.py; AE3 verification.

[CONSTRAINTS block]
```

---

## Phase 4 workers

### Worker U24

```text
WORKER U24 — Ads service (extract from bot).

Read plan 002 § U24. POST /internal/ads/submit; transcode; PG ads table; injector enqueue.

services/ads/*, bot ads_client, remove bot direct injector for ads.

Verify: pytest test_ads_*; AE1 still passes.

[CONSTRAINTS block]
```

### Worker U25

```text
WORKER U25 — Operator /city + auth allowlists.

Read plan 002 § U25, operator-contract §2.

bot handlers/city.py, middleware/auth.py, operator_prefs DB, tests/test_bot_city.py.

[CONSTRAINTS block]
```

### Worker U26

```text
WORKER U26 — Voice ad production flow (confirm mandatory).

Read plan 002 § U26. conversation state; ads service integration; tests/test_bot_voice_flow.py.

[CONSTRAINTS block]
```

### Worker U27

```text
WORKER U27 — /status + /playlist admin.

Read plan 002 § U27. metadata_client; admin check TELEGRAM_ADMIN_IDS; tests.

[CONSTRAINTS block]
```

### Worker U28

```text
WORKER U28 — Metadata queue preview API.

Read plan 002 § U28, docs/openapi.yaml — add GET /api/queue/{cityTag}.

services/metadata/queue_reader.py, tests/test_metadata.py, remaining_sec on now-playing.

[CONSTRAINTS block]
```

### Worker U29

```text
WORKER U29 — Multi-city ops.

Read plan 002 § U29. cities.yaml third city template; dynamic bot keyboards; tests/test_multi_city.py; deploy/README.md §adding a city.

[CONSTRAINTS block]
```

---

## Phase 5 workers

### Worker U30

```text
WORKER U30 — Production deploy + HTTPS Telegram webhook.

Read plan 002 § U30, ADR-003.

deploy/production/*, nginx TLS, env.template, set_telegram_webhook.sh, webhook secret validation.

Document staging smoke checklist. Do NOT commit secrets.

[CONSTRAINTS block]
```

### Worker U31

```text
WORKER U31 — Monitoring + health aggregation.

Read plan 002 § U31.

services/metadata/health.py, JSON logging, optional prometheus configs, docs/runbooks/stream-down.md, tests/test_health.py.

[CONSTRAINTS block]
```

### Worker U32

```text
WORKER U32 — Cron cleanup jobs (TZ §9).

Read plan 002 § U32.

services/cron/*, docker/cron.Dockerfile, tests/test_cron_cleanup.py with frozen time.

[CONSTRAINTS block]
```

### Worker U33

```text
WORKER U33 — Gateway rate limits (prod nginx).

Read plan 002 § U33. limit_req on geo + webhook paths.

[CONSTRAINTS block]
```

### Worker U34

```text
WORKER U34 — E2E acceptance TZ §12 sign-off.

Read plan 002 § U34, spec/acceptance.yaml.

Full checklist mapping; tests/e2e/full-product.spec.ts; undefer remaining AEs; README production quickstart.

Orchestrator runs final review — worker prepares artifacts and checklist only.

[CONSTRAINTS block]
```

---

## Когда фаза vs когда один юнит

| Ситуация | Рекомендация |
|----------|----------------|
| Обычная разработка | **1 сессия = 1 фаза**, оркестратор + workers |
| Мало времени / узкий фикс | 1 сессия = 1 юнит, worker prompt без оркестратора |
| Phase 3 news | Только фазой — длинная цепочка U15–U23 |
| Phase 0 ретро | Отдельная короткая сессия doc-review |

Оркестратор на фазу — правильный default: он держит порядок U, parallelization, phase exit и не даёт «забыть» review между юнитами.
