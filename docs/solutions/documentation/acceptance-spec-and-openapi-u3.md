---
title: U3 acceptance spec and OpenAPI cross-linking patterns
date: 2026-06-08
category: documentation
module: spec
problem_type: best_practice
component: documentation
symptoms:
  - "Agents cannot trace requirements AE1–AE6 to machine-parseable verification"
  - "Contract markdown anchors break when copied without full GitHub slug suffix"
resolution_type: documentation
severity: low
tags: [acceptance, openapi, contracts, traceability, u3]
---

# U3 acceptance spec and OpenAPI cross-linking patterns

## Problem

Phase 0 needed machine-parseable acceptance criteria and a Phase 1 public API contract without leaking internal enqueue endpoints. Contracts (U2) and requirements used narrative AE examples; implementers needed a single traceability layer for CI and agents.

## Solution

1. **`spec/acceptance.yaml`** — structured entries per AE with `covers`, `contract_refs`, `verification`, `units`, and `phase`. Plan extras use stable IDs (`AE-QUEUE-FULL`, `AE-ALL-FANOUT`, `AE-CITY-SWITCH`). Phase 2+ origin AEs stay present but `deferred: true`.

2. **`docs/openapi.yaml`** — OpenAPI 3.1 for listener APIs only (`/api/geo/*`, `/api/now-playing/{cityTag}`, `/api/health`). Internal `POST /internal/enqueue` explicitly excluded in `info.description`.

3. **Bidirectional links** — contracts §9/§10 acceptance tables link to spec IDs; spec `contract_refs` use full GitHub-style anchors (e.g. `#3-city-detection-order-r1`, not `#3-city-detection-order`).

4. **Traceability edge cases**
   - AE5 maps to Key Decision `synchronous-radio` via `covers_decision` (no standalone R-ID).
   - R37 split across `AE4`, `AE-CITY-SWITCH`, `AE-NOW-PLAYING`.
   - Injector vs bot assertions split (`then` vs `bot_then`) when units differ (U5 vs U8).

## Why This Works

Agents read contracts for behavior and `acceptance.yaml` for verifiable gates. OpenAPI gives U6/U7 a concrete HTTP contract; cross-links prevent drift between narrative contracts and executable checks.

## Prevention

- When adding contract sections, update acceptance mapping tables and spec entries in the same unit.
- Copy markdown anchor slugs from rendered headings (include parenthetical suffixes).
- Keep `verification` clauses automatable for Phase 1; mark long manual checks (10 min background tab) with separate CI vs release steps.
- Sync `CityTag` OpenAPI enum with `broadcast/liquidsoap/cities.yaml` until codegen exists.

## Related Issues

- Plan U3: `docs/plans/2026-06-08-001-feat-fm21-greenfield-plan.md`
- Requirements AE1–AE6: `docs/brainstorms/2026-06-08-fm21-requirements.md`
