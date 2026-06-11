---
date: 2026-06-11
status: completed
type: feat
title: "feat: TDD agent workflow + verification gates"
origin: session/2026-06-11-broadcast-player-debug
---

# Plan: TDD Agent Workflow + Verification Gates

## Summary

Close the gap between agent Definition of Done and bugs caught only in manual/browser testing (gateway 502, `fm21.liq` compile crash, news truncation, materialize rotation). Add **test-first policy**, **layer gates**, **automated acceptance runner**, **e2e stream playback**, and **CI**.

## Problem Frame

Python unit tests cover services but not broadcast/nginx/Liquidsoap cross-layer contracts. Orchestrator verify steps allow `pytest` green while liquidsoap crash-loops and gateway returns 502. Workers implement before testing; e2e is phase-exit optional.

## Scope

| In scope | Out of scope |
|----------|--------------|
| AGENTS.md + orchestrator TDD/gates | Retrofitting all plan 002 units with Execution notes |
| pytest infrastructure + news regression tests | Full `news-slot.spec.ts` with live TTS |
| `scripts/verify_acceptance.sh` | Production deploy changes |
| e2e stream playback (moscow + spb) | Host-native test commands as primary path |
| GitHub Actions CI | Babysit PR merge |

## Key Technical Decisions

| ID | Decision | Rationale |
|----|----------|-----------|
| KTD-T1 | Layer gates in Docker only | ADR-003; no host pytest |
| KTD-T2 | `liquidsoap --check` in pytest + CI | Catches type errors before runtime |
| KTD-T3 | Config contract tests (nginx, fm21.liq text) | Fast, no live stack for unit tier |
| KTD-T4 | `verify_acceptance.sh --phase N` | Makes acceptance.yaml executable |
| KTD-T5 | TDD block in worker prompts | Forces red-before-green at dispatch |

## Implementation Units

### U-TDD-1 — Agent workflow docs

**Goal:** Encode TDD + layer gates in orchestrator and AGENTS runbook.

**Execution note:** Docs only; verify link consistency.

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/prompts/orchestrator-phases.md`

**Approach:**
- Extend Definition of Done: RED → GREEN → VERIFY → LAYER → REVIEW
- Add Phase Exit Gates A–E (pytest, liquidsoap --check, gateway curl mounts, e2e, acceptance script)
- Add TDD mandatory block to shared orchestrator rules and Worker template
- Document `scripts/verify_acceptance.sh` in Commands

**Test scenarios:** N/A (doc verification: internal links resolve)

**Verification:** Read-back checklist; links to new script and test files exist.

---

### U-TDD-2 — Infrastructure contract tests (pytest)

**Goal:** Catch nginx proxy and Liquidsoap compile/annotate regressions in `docker compose run --rm test pytest`.

**Execution note:** test-first — write failing tests, then fix only if config already correct (tests should pass on current fixed tree).

**Files:**
- Create: `tests/test_broadcast_gates.py`
- Modify: `docker/python.Dockerfile` (test target: ensure liquidsoap image available OR shell out via compose — prefer reading files + subprocess only if liquidsoap in test image; **use file content assertions + optional skip if no liquidsoap binary**)

**Approach:**
- Assert `docker/nginx-gateway.conf` uses static `location = /{city}` without `$request_uri` in proxy_pass
- Assert `fm21.liq` omits `duration=` for NEWS_PAIR main annotate branch
- Subprocess `liquidsoap --check` when `LIQUIDSOAP_CHECK=1` or skip in unit container; **add test that runs via compose profile** — document in test with marker `integration`
- Create `tests/test_broadcast_integration.sh` invoked from pytest or `scripts/verify_acceptance.sh` for live liquidsoap --check

**Test scenarios:**
- nginx mount locations are static upstream paths
- fm21.liq NEWS_PAIR main branch has no duration in annotate string
- liquidsoap --check exits 0 (integration marker)

**Verification:** `docker compose run --rm test pytest tests/test_broadcast_gates.py -v`

---

### U-TDD-3 — News pipeline regression tests

**Goal:** Guard materialize rotation and duration probing.

**Execution note:** test-first for new scenarios.

**Files:**
- Modify: `tests/test_news_materialize.py`
- Modify: `tests/test_news_enqueue.py`

**Approach:**
- Add `test_materialize_two_slots_pins_different_items_when_fetched_exists` (seed fetched + ready; two select_for_materialize calls return different ids when fetched consumed)
- Add `test_build_news_pair_payload_uses_ceiled_probe_duration` with fixture mp3 bytes or mock probe

**Test scenarios:**
- Materialize advances pipeline when fetched backlog exists
- Enqueue duration uses ceil of probed seconds

**Verification:** `docker compose run --rm test pytest tests/test_news_materialize.py tests/test_news_enqueue.py -v`

---

### U-TDD-4 — E2E stream playback

**Goal:** Browser gate: Play works on moscow and spb; no reconnect error text.

**Execution note:** test-first — add spec, run e2e red if needed, fix player/gateway only if failing.

**Files:**
- Create: `tests/e2e/stream-playback.spec.ts`
- Modify: `tests/e2e/geo-isolation.spec.ts` (assert no retry status after play; afterAll close)

**Approach:**
- New spec: open gateway, play moscow → `!paused`, status empty; switch spb → play → `!paused`
- Assert `document.getElementById('status').textContent` does not match /Повтор подключения/

**Test scenarios:**
- moscow stream plays via gateway
- spb stream plays via gateway
- No reconnect loop message after successful play

**Verification:** `docker compose run --rm e2e` (requires stack up)

---

### U-TDD-5 — Acceptance verification script

**Goal:** Executable mapping from `spec/acceptance.yaml` to docker commands.

**Files:**
- Create: `scripts/verify_acceptance.sh`
- Modify: `spec/acceptance.yaml` (add automated bindings for gateway smoke, liquidsoap check where missing)

**Approach:**
- `--phase N` runs pytest/e2e/curl gates for that phase's non-deferred AEs
- `--strict` fails on `manual:` bindings without `--allow-manual`
- Gates: pytest subsets, `liquidsoap --check`, gateway GET /moscow /spb

**Test scenarios:**
- Script exits 0 on healthy dev stack
- `--strict` documents manual gaps

**Verification:** `bash scripts/verify_acceptance.sh --phase 1` (subset); document full phase 3 in AGENTS

---

### U-TDD-6 — GitHub Actions CI

**Goal:** Machine-enforce gates on push/PR.

**Execution note:** implement after tests land.

**Files:**
- Create: `.github/workflows/ci.yml`

**Approach:**
- Job: build images, `docker compose run --rm test pytest`
- Job or step: `liquidsoap --check` via compose
- Optional e2e job with compose up (if runtime acceptable; else document as nightly)

**Test scenarios:**
- CI yaml valid; pytest job runs on PR

**Verification:** `gh workflow view` or local `act` if available; at minimum yaml lint + dry review

---

## Dependencies

```
U-TDD-1 ─┐
U-TDD-2 ─┼─► U-TDD-5 ─► U-TDD-6
U-TDD-3 ─┤
U-TDD-4 ─┘
```

U-TDD-1/2/3/4 parallel. U-TDD-5 after test paths known. U-TDD-6 last.

## Phase Exit Verification (orchestrator)

```bash
docker compose run --rm test pytest tests/ -q
docker compose run --rm --no-deps liquidsoap liquidsoap --check /broadcast/liquidsoap/fm21.liq
bash scripts/verify_acceptance.sh --phase 3 --allow-manual
docker compose run --rm e2e
```
