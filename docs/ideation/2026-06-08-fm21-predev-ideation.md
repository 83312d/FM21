---
date: 2026-06-08
topic: fm21-predev
focus: stack, docs/specs, agent workflow (compound-engineering; ignore tz.md Node stack)
mode: repo-grounded
---

# Ideation: FM21 Pre-Development Preparation

## Grounding Context

**Codebase:** Greenfield repo — only `docs/tz.md` (v1.1), compound-engineering plugin enabled, zero commits, no `AGENTS.md`/`STRATEGY.md`/`README.md`.

**Product:** FM21 — geotargeted internet radio (music + IT news every 15 min + voice ads via Telegram). Per-city queues (`city_tag`), priority AD > NEWS > MUSIC_ORDER > MUSIC, no mid-track interruption.

**User goal:** Brainstorm before development; choose stack independently of tz.md; build docs/specs; configure agent workflow via [compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin).

**External context:** Liquidsoap+Icecast proven for autonomous radio; Yandex Music has no commercial API; ADR-first + STRATEGY.md → ce-brainstorm → ce-plan → ce-work pipeline; HLS 15–30s vs ICY 2–5s latency tradeoff.

## Topic Axes

1. Архитектура эфира — broadcast model, streaming protocol, multi-city isolation
2. Стек и музыка — runtime, music licensing, infrastructure
3. Документация и спеки — STRATEGY, ADRs, API contracts, acceptance criteria
4. Агентный воркфлоу — compound-engineering pipeline, rules, phased execution
5. Порядок поставки — prototype/decide order, risk sequencing

## Ranked Ideas

### 1. ADR Delivery Model Gate (нулевой этап)

**Description:** Первый milestone — не код, а ADR с выбором модели доставки: (A) multi-mount Icecast — синхронное радио per `city_tag`; (B) personalized HLS manifest — один URL, разные вставки; (C) client-side stitching — как в tz.md. Два параллельных PoC-отчёта → синтез `docs/adr/001-delivery-model.md`. Код с `queue`/`stream` в названии — только после merge ADR.

**Axis:** Агентный воркфлоу · Порядок поставки

**Basis:** `direct:` tz §11 начинает с «каркас Node.js», предполагая решённые архитектурные вилки · `external:` Fowler ADR process; Nearform spec-driven development — decisions before implementation

**Rationale:** Ошибка в delivery model стоит 40–60% переделки после этапа 3. $200 агентного research сейчас vs месяцы refactor.

**Downsides:** Задержка первого коммита на 1–3 дня; требует дисциплины «не писать код раньше ADR».

**Confidence:** 92%

**Complexity:** Low (process, not code)

**Status:** Explored

---

### 2. Liquidsoap + Icecast «Radio Spine»

**Description:** Заменить кастомный Broadcast Engine на Liquidsoap (очередь, приоритеты, crossfade, HLS/ICY output) + Icecast mount per `city_tag`. Сервисы (News, Bot, Music) только пушат URI в harbor/telnet. Плеер — `<audio>` или hls.js, без Web Audio stitching. WS — только метаданные (now-playing, queue preview).

**Axis:** Архитектура эфира

**Basis:** `direct:` tz §2.1 Broadcast Engine, §4.2 Queue Manager, §6.4 Web Audio · `external:` Liquidsoap `request.queue`, crossfade, HLS output; Icecast mount-per-city pattern

**Rationale:** Снимает два самых рискованных greenfield-компонента (stream muxer + client audio graph) при сохранении бизнес-правил §4.1.

**Downsides:** Liquidsoap — отдельный DSL; меньше контроля над edge cases; HLS latency 6–15s если не ICY.

**Confidence:** 85%

**Complexity:** Medium

**Status:** Explored

---

### 3. MusicProvider Licensing Fork (блокер до этапа 2)

**Description:** До любой музыкальной интеграции — ADR-002 с явным выбором: (A) royalty-free/CC каталог для MVP; (B) Yandex OAuth (только friends-only beta, ToS risk); (C) licensed B2B (Feed.fm и аналоги); (D) self-hosted library. Интерфейс `MusicProvider` — день один, Yandex — адаптер, не дефолт.

**Axis:** Стек и музыка

**Basis:** `direct:` tz §3.2 Yandex proxy, §13 licensing risk · `external:` нет официального Yandex Music API; commercial re-streaming = ToS violation; Feed.fm B2B path

**Rationale:** Без легального источника музыки половина tz (tracks_cache, stream_url_expires, /order) переписывается. Блокер #1 по риску.

**Downsides:** Royalty-free MVP слабее продуктовая демо; Feed.fm — платно и quote-based.

**Confidence:** 90%

**Complexity:** Low (decision) / High (licensing negotiation)

**Status:** Explored

---

### 4. Contract-First Spec Decomposition

**Description:** Разбить tz.md на три контракта вместо «4 сервиса + оркестратор»: (1) **Broadcast Semantics** — приоритеты, no-interrupt, расписание; (2) **Listener Contract** — geo, autoplay, фон, now-playing; (3) **Operator Contract** — команды бота, лимиты. Добавить `openapi.yaml` для §7 API и `spec/acceptance.yaml` из §12 критериев. tz.md остаётся input для ce-brainstorm, не agent context root.

**Axis:** Документация и спеки

**Basis:** `direct:` tz смешивает бизнес-правила с Node/HLS/Redis implementation · `external:` Spec-as-prompt; AGENTS.md as TOC pointing to docs/adr/, docs/plans/

**Rationale:** При смене Liquidsoap/Icecast контракты (1–3) остаются валидными; агенты получают verifiable targets вместо 311 строк prose.

**Downsides:** Upfront work ~1–2 дня; дублирование с tz до полной миграции.

**Confidence:** 88%

**Complexity:** Medium

**Status:** Explored

---

### 5. Vertical Geo Slice (2 города + 1 объявление)

**Description:** Вместо линейных этапов tz §11 — первый proof: Москва + СПб, статический плейлист (без Yandex), бот шлёт объявление только в Москву, слушатель СПб не слышит. Демо гео-изоляции за неделю, до news cron / TTS / Yandex.

**Axis:** Порядок поставки

**Basis:** `direct:` tz §1 «главное правило — геотаргетинг», но §11 ставит мультигород на этап 6 · `reasoned:` если гео-изоляция в эфире не работает — остальные модули бессмысленны

**Rationale:** Валидирует core product invariant раньше, чем интеграции с внешними API. Демо для стейкхолдеров без Yandex/TTS.

**Downsides:** Не показывает полный UX (новости, заказы); требует минимального broadcast spine (#2).

**Confidence:** 87%

**Complexity:** Medium

**Status:** Explored

---

### 6. Compound-Engineering Bootstrap Pipeline

**Description:** Явный agent workflow: `/ce-strategy` → `/ce-brainstorm docs/tz.md` → `/ce-plan` (фазы = vertical slices, не tz §11) → `/ce-work` → `/ce-code-review` → `/ce-compound` после каждой фазы. Создать `STRATEGY.md`, `AGENTS.md` (~100 строк TOC), `docs/adr/`, `docs/plans/`, `docs/solutions/`. Human gatekeeps: ADRs, `.env`, `playlist-rules` config.

**Axis:** Агентный воркфлоу

**Basis:** `direct:` repo has compound-engineering plugin, empty config · `external:` EveryInc workflow — STRATEGY upstream, 40% plan / 40% review / 10% work / 10% compound

**Rationale:** Без upstream docs каждая Cursor-сессия переизобретает intent из tz. Compound checkpoints превращают решения в institutional memory.

**Downsides:** Overhead для solo dev; риск «документировать вместо строить» без time-box.

**Confidence:** 86%

**Complexity:** Low

**Status:** Explored

---

### 7. Sync Radio vs Async Timeline (продуктовое решение)

**Description:** Явно зафиксировать: (A) **синхронное радио** — все слушатели города слышат один трек в одну секунду (→ Icecast mount); (B) **асинхронный эфир** — у каждого свой timeline от момента Play (→ client stitching / personalized manifest). Тест: «Иван заказал песню в 14:03 — Петя, включивший в 14:05, услышит её?»

**Axis:** Архитектура эфира

**Basis:** `direct:` tz смешивает «заказ в очередь всех слушателей города» (sync) с Web Audio stitching (async) · `external:` ZoneCasting / Super Hi-Fi HLS+ models

**Rationale:** Разные ответы → разная архитектура (#1 ADR), разный `/status` в боте, разный UX «мы в эфире вместе».

**Downsides:** Sync усложняет idle-city infra; async усложняет «сейчас играет у всех».

**Confidence:** 84%

**Complexity:** Low (decision) / cascades to High (implementation)

**Status:** Explored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | 100 cities day one | Scope overrun for pre-dev |
| 2 | Agent owns 90% of repo | Brainstorm variant, not standalone |
| 3 | Wwise/FMOD stack analogy | Too vague |
| 4 | KDS / change-ringing metaphors | Terminology only |
| 5 | Theatre cue script | Duplicate of #4 executable spec |
| 6 | Monolith-in-a-box | Weaker than Liquidsoap spine |
| 7 | Metadata-only WS alone | Sub-component of #2 |
| 8 | Telegram city memory | Tactical, below bar |
| 9 | OpenAPI-first alone | Merged into #4 |
| 10 | ATIS phase-lock / news bank | Deferred to brainstorm of broadcast |
